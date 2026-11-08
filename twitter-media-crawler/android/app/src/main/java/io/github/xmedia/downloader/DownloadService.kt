package io.github.xmedia.downloader

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.chaquo.python.PyException
import com.chaquo.python.PyObject
import org.json.JSONObject
import java.io.File
import java.util.concurrent.atomic.AtomicLong

/**
 * 다운로드를 실행하는 포그라운드 서비스. 화면을 끄거나 다른 앱으로 가도 계속 받는다.
 * 요청은 줄을 세워 하나씩 처리한다 (예: 받는 중에 X 앱에서 다른 게시물을 공유한 경우).
 *
 * 스레드: onStartCommand / requestStop / onWorkerFinished / finishService 는 메인 스레드,
 * workLoop / runJob / Listener 는 작업 스레드 하나에서 돈다.
 */
class DownloadService : Service() {
    companion object {
        const val ACTION_START = "io.github.xmedia.downloader.action.START"
        const val ACTION_STOP = "io.github.xmedia.downloader.action.STOP"
        const val EXTRA_TARGET = "target"
        private const val NOTIFY_INTERVAL_MS = 1000L
        private const val WAKE_LOCK_TIMEOUT_MS = 6 * 60 * 60 * 1000L // 안드로이드의 하루 제한과 같은 6시간
        private val jobIds = AtomicLong(0)

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

    private data class Job(val id: Long, val target: String, val login: Settings.Login?)

    private val main = Handler(Looper.getMainLooper())
    private val queue = ArrayDeque<Job>() // 메인 스레드와 작업 스레드가 함께 쓰므로 synchronized(queue)
    private var worker: Thread? = null // 메인 스레드에서만 읽고 쓴다
    private var lastStartId = 0
    private var wakeLock: PowerManager.WakeLock? = null
    @Volatile private var stopRequested = false
    @Volatile private var currentJobId = -1L
    @Volatile private var isForeground = false
    @Volatile private var lastNotify = 0L
    @Volatile private var hasNewResult = false // 결과 알림을 띄울 실행이 있었는지
    private var destroyed = false // 시간 제한 등으로 서비스가 먼저 끝난 뒤에도 작업 스레드는 마저 정리된다

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        lastStartId = startId
        when (intent?.action) {
            ACTION_START -> {
                // startForegroundService() 후 몇 초 안에 반드시 포그라운드로 전환해야 한다
                goForeground("준비 중…")
                val target = intent.getStringExtra(EXTRA_TARGET).orEmpty()
                // 로그인 쿠키는 WebView(메인 스레드)에서 읽어 둔다
                val job = Job(jobIds.incrementAndGet(), target, XLogin.current(this))
                val size = synchronized(queue) {
                    if (queue.none { it.target == target }) queue.addLast(job)
                    queue.size
                }
                stopRequested = false
                DownloadState.preparing() // 엔진 준비(첫 실행 땐 몇 초)동안에도 화면이 '진행 중'을 보여주도록
                DownloadState.setQueued(size)
                ensureWorker()
            }
            ACTION_STOP -> requestStop()
            else -> if (worker == null) stopSelf(startId) // 시스템이 서비스를 다시 만든 경우 등
        }
        return START_NOT_STICKY
    }

    private fun goForeground(text: String) {
        if (!isForeground) {
            ServiceCompat.startForeground(
                this,
                Notifications.ID_PROGRESS,
                Notifications.progress(this, text),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
            isForeground = true
        } else {
            Notifications.update(this, text)
        }
    }

    private fun ensureWorker() {
        if (worker?.isAlive == true) return
        acquireWakeLock()
        worker = Thread({ workLoop() }, "xmedia-download").apply { start() }
    }

    /** 화면이 꺼져도 CPU가 잠들지 않게 (포그라운드 서비스만으로는 CPU가 깨어 있지 않다). */
    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val pm = getSystemService(PowerManager::class.java)
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "XMedia:download").apply {
            setReferenceCounted(false)
            acquire(WAKE_LOCK_TIMEOUT_MS)
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    private fun requestStop() {
        stopRequested = true
        synchronized(queue) { queue.clear() }
        DownloadState.setQueued(0)
        DownloadState.stopRequested()
        if (worker?.isAlive == true) {
            // stopRequested를 먼저 세운 뒤 작업 번호를 읽는다: 작업 스레드는 번호를 정한 다음 stopRequested를 확인하므로
            // 둘 중 하나는 반드시 중지를 알아챈다. 파이썬 쪽은 엔진 준비 중에 온 중지도 번호로 기억한다.
            val jobId = currentJobId
            Thread({
                try {
                    Engine.bridge(applicationContext).callAttr("stop", jobId)
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
            // 엔진을 시작하지 못했으면 남은 요청도 같은 이유로 실패하므로 비운다 (무한 재시도 방지)
            synchronized(queue) { queue.clear() }
            hasNewResult = true
            val msg = if (t is PyException) Pure.pythonErrorMessage(t.message) else (t.message ?: t.javaClass.simpleName)
            DownloadState.finishRun("엔진을 시작하지 못했습니다: $msg", ok = false)
        } finally {
            val me = Thread.currentThread()
            main.post { onWorkerFinished(me) }
        }
    }

    private fun runJob(bridge: PyObject, staging: File, job: Job) {
        val label = if (job.target == "bookmarks") "내 북마크" else job.target.lineSequence().first().take(80)
        currentJobId = job.id
        hasNewResult = true
        if (stopRequested) {
            DownloadState.finishRun("중지됨", ok = true)
            return
        }
        DownloadState.begin(label)
        main.post { if (isForeground) goForeground("받는 중: $label") }
        val login = job.login
        if (login == null) {
            DownloadState.finishRun("X 로그인이 필요합니다. 앱에서 'X 로그인'을 먼저 해 주세요.", ok = false)
            return
        }
        val settings = Settings(this)
        val options = JSONObject()
            .put("target", job.target)
            .put("media", settings.media)
            .put("retweets", settings.retweets)
            .put("quick_refresh", settings.quickRefresh)
            .put("auth_token", login.authToken)
            .put("ct0", login.ct0)
        try {
            val resultJson = bridge.callAttr("run_download", staging.absolutePath, options.toString(), Listener(), job.id)
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
            // 포그라운드를 내려놓은 뒤(시간 제한 등)에는 진행 알림을 다시 띄우지 않는다
            if (isForeground && now - lastNotify >= NOTIFY_INTERVAL_MS) {
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

    private fun onWorkerFinished(thread: Thread) {
        if (worker !== thread) return // 그사이 새 작업 스레드가 시작됐다
        worker = null
        val pending = synchronized(queue) { queue.isNotEmpty() }
        if (pending && !stopRequested) {
            ensureWorker() // 마지막 작업이 끝나는 사이에 새 요청이 들어온 경우
            return
        }
        finishService()
    }

    /** 포그라운드 알림과 wake lock을 내려놓는다. */
    private fun dropForeground() {
        isForeground = false
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        NotificationManagerCompat.from(this).cancel(Notifications.ID_PROGRESS)
        releaseWakeLock()
    }

    private fun finishService() {
        // 아직 처리하지 않은 새 시작 요청이 배달돼 있으면 멈추지 않는다 (그 요청이 이어서 실행된다).
        // 이미 끝난 서비스에서는 stopSelfResult가 항상 false라서 확인하지 않는다.
        if (!destroyed && !stopSelfResult(lastStartId)) return
        DownloadState.idle()
        DownloadState.setQueued(0)
        dropForeground()
        if (hasNewResult && DownloadState.lastSummary.isNotEmpty()) {
            Notifications.showResult(applicationContext, DownloadState.lastSummary, DownloadState.lastOk)
        }
        hasNewResult = false
    }

    /** 안드로이드 15+: 데이터 동기화 서비스는 하루 6시간 제한이 있다. 시간이 다 되면 멈춘다. */
    override fun onTimeout(startId: Int, fgsType: Int) {
        // 몇 초 안에 포그라운드를 내려놓지 않으면 시스템이 앱을 강제로 끝낸다. 작업 스레드는 기다리지 않고,
        // '진행 중' 상태는 작업 스레드가 실제로 끝날 때(onWorkerFinished) 정리된다.
        requestStop()
        DownloadState.note("! 안드로이드의 백그라운드 작업 시간 제한(하루 6시간)에 걸려 멈췄습니다. 나중에 다시 시작하면 이어서 받습니다.")
        dropForeground()
        stopSelf()
    }

    override fun onDestroy() {
        destroyed = true
        if (worker?.isAlive == true) requestStop()
        dropForeground()
        super.onDestroy()
    }
}
