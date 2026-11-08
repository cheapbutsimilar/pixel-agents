package io.github.xmedia.downloader

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.chaquo.python.PyException
import org.json.JSONObject
import java.io.File

/**
 * 다운로드를 실행하는 포그라운드 서비스. 화면을 끄거나 다른 앱으로 가도 계속 받는다.
 * 요청은 줄을 세워 하나씩 처리한다 (예: 받는 중에 X 앱에서 다른 게시물을 공유한 경우).
 */
class DownloadService : Service() {
    companion object {
        const val ACTION_START = "io.github.xmedia.downloader.action.START"
        const val ACTION_STOP = "io.github.xmedia.downloader.action.STOP"
        const val EXTRA_TARGET = "target"
        private const val NOTIFY_INTERVAL_MS = 1000L

        fun start(context: Context, target: String) {
            val intent = Intent(context, DownloadService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_TARGET, target)
            ContextCompat.startForegroundService(context, intent)
        }

        fun stop(context: Context) {
            if (!DownloadState.running) return
            context.startService(Intent(context, DownloadService::class.java).setAction(ACTION_STOP))
        }
    }

    private data class Job(val target: String, val login: Settings.Login?)

    private val main = Handler(Looper.getMainLooper())
    private val queue = ArrayDeque<Job>() // 메인 스레드와 작업 스레드가 함께 쓰므로 synchronized(queue)
    private var worker: Thread? = null // 메인 스레드에서만 읽고 쓴다
    @Volatile private var stopRequested = false
    @Volatile private var lastNotify = 0L
    private var isForeground = false
    @Volatile private var hasNewResult = false // 결과 알림을 띄울 실행이 있었는지

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                // startForegroundService() 후 몇 초 안에 반드시 포그라운드로 전환해야 한다
                goForeground("준비 중…")
                val target = intent.getStringExtra(EXTRA_TARGET).orEmpty()
                // 로그인 쿠키는 WebView(메인 스레드)에서 읽어 둔다
                val job = Job(target, XLogin.current(this))
                val size = synchronized(queue) {
                    if (queue.none { it.target == target }) queue.addLast(job)
                    queue.size
                }
                DownloadState.setQueued(size)
                stopRequested = false
                ensureWorker()
            }
            ACTION_STOP -> requestStop()
            else -> if (worker == null) stopSelf() // 시스템이 서비스를 다시 만든 경우 등
        }
        return START_NOT_STICKY
    }

    private fun goForeground(text: String) {
        val notification = Notifications.progress(this, text)
        if (!isForeground) {
            ServiceCompat.startForeground(
                this,
                Notifications.ID_PROGRESS,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
            isForeground = true
        } else {
            Notifications.update(this, text)
        }
    }

    private fun ensureWorker() {
        if (worker?.isAlive == true) return
        worker = Thread({ workLoop() }, "xmedia-download").apply { start() }
    }

    private fun requestStop() {
        stopRequested = true
        synchronized(queue) { queue.clear() }
        DownloadState.setQueued(0)
        DownloadState.stopRequested()
        if (worker?.isAlive == true) {
            // 파이썬 호출은 잠깐 기다릴 수 있으므로 메인 스레드에서 하지 않는다
            Thread({
                try {
                    Engine.bridge(applicationContext).callAttr("stop")
                } catch (_: Exception) {
                }
            }, "xmedia-stop").start()
        } else {
            finishService()
        }
    }

    private fun workLoop() {
        try {
            val bridge = Engine.bridge(applicationContext)
            val staging = Engine.stagingDir(this)
            publishLeftovers(staging)
            while (!stopRequested) {
                val job = synchronized(queue) { queue.removeFirstOrNull() } ?: break
                DownloadState.setQueued(synchronized(queue) { queue.size })
                runJob(bridge, staging, job)
                publishLeftovers(staging)
            }
        } catch (t: Throwable) {
            val msg = if (t is PyException) Pure.pythonErrorMessage(t.message) else (t.message ?: t.javaClass.simpleName)
            DownloadState.finishRun("엔진을 시작하지 못했습니다: $msg", ok = false)
        } finally {
            main.post { onWorkerFinished() }
        }
    }

    private fun runJob(bridge: com.chaquo.python.PyObject, staging: File, job: Job) {
        val label = if (job.target == "bookmarks") "내 북마크" else job.target.lineSequence().first().take(80)
        DownloadState.begin(label)
        main.post { goForeground("받는 중: $label") }
        val login = job.login
        if (login == null) {
            hasNewResult = true
            DownloadState.finishRun("X 로그인이 필요합니다. 앱에서 'X 로그인'을 먼저 해 주세요.", ok = false)
            return
        }
        hasNewResult = true
        val settings = Settings(this)
        val options = JSONObject()
            .put("target", job.target)
            .put("media", settings.media)
            .put("retweets", settings.retweets)
            .put("quick_refresh", settings.quickRefresh)
            .put("auth_token", login.authToken)
            .put("ct0", login.ct0)
        try {
            val resultJson = bridge.callAttr("run_download", staging.absolutePath, options.toString(), Listener())
            val result = JSONObject(resultJson.toString())
            val ok = result.optInt("returncode", 1) == 0 || result.optBoolean("stopped")
            DownloadState.finishRun(result.optString("summary"), ok)
        } catch (e: PyException) {
            DownloadState.finishRun("시작하지 못했습니다: ${Pure.pythonErrorMessage(e.message)}", ok = false)
        } catch (e: Exception) {
            DownloadState.finishRun("실행 중 오류: ${e.message ?: e.javaClass.simpleName}", ok = false)
        }
    }

    private fun publishLeftovers(staging: File) {
        val count = MediaPublisher.publishLeftovers(this, staging) { file, e ->
            DownloadState.note("! 사진 앱으로 옮기지 못함 (다음에 다시 시도): ${file.name} — ${e.message}")
        }
        if (count > 0) DownloadState.note("지난번에 남은 파일 ${count}개를 사진 앱으로 옮겼습니다")
    }

    /** 파이썬(android_bridge.run_download)이 부르는 콜백. 작업 스레드에서 호출된다. */
    inner class Listener {
        fun onEvent(kind: String, text: String) {
            DownloadState.event(kind, text)
            val now = SystemClock.elapsedRealtime()
            if (now - lastNotify >= NOTIFY_INTERVAL_MS) {
                lastNotify = now
                Notifications.update(this@DownloadService, DownloadState.status)
            }
        }

        fun onFile(path: String, folder: String) {
            try {
                MediaPublisher.publish(this@DownloadService, File(path), folder)
            } catch (e: Exception) {
                DownloadState.note("! 사진 앱으로 옮기지 못함 (다음에 다시 시도): ${File(path).name} — ${e.message}")
            }
        }
    }

    private fun onWorkerFinished() {
        worker = null
        val pending = synchronized(queue) { queue.isNotEmpty() }
        if (pending && !stopRequested) {
            ensureWorker() // 마지막 작업이 끝나는 사이에 새 요청이 들어온 경우
            return
        }
        finishService()
    }

    private fun finishService() {
        DownloadState.idle()
        DownloadState.setQueued(0)
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        isForeground = false
        if (hasNewResult && DownloadState.lastSummary.isNotEmpty()) {
            Notifications.showResult(this, DownloadState.lastSummary, DownloadState.lastOk)
        }
        hasNewResult = false
        stopSelf()
    }

    /** 안드로이드 15+: 데이터 동기화 서비스는 하루 6시간 제한이 있다. 시간이 다 되면 멈춘다. */
    override fun onTimeout(startId: Int, fgsType: Int) {
        // 몇 초 안에 포그라운드를 내려놓지 않으면 시스템이 앱을 강제로 끝낸다. 작업 스레드를 기다리지 않는다.
        requestStop()
        DownloadState.note("! 안드로이드의 백그라운드 작업 시간 제한(하루 6시간)에 걸려 멈췄습니다. 내일 이어서 받으세요.")
        finishService()
    }

    override fun onDestroy() {
        if (worker?.isAlive == true) requestStop()
        super.onDestroy()
    }
}
