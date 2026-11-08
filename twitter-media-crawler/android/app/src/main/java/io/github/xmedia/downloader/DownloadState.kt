package io.github.xmedia.downloader

import android.os.Handler
import android.os.Looper
import java.util.concurrent.CopyOnWriteArraySet

/** 다운로드 진행 상황 (서비스가 쓰고 화면이 읽는다). 같은 프로세스 안에서만 쓴다. */
object DownloadState {
    private const val MAX_LOG_LINES = 400
    private const val NOTIFY_DELAY_MS = 150L

    private val main = Handler(Looper.getMainLooper())
    private val listeners = CopyOnWriteArraySet<() -> Unit>()
    private val log = ArrayDeque<String>()
    @Volatile private var notifyPending = false

    @Volatile var running = false; private set
    @Volatile var stopping = false; private set
    @Volatile var target = ""; private set
    @Volatile var downloaded = 0; private set
    @Volatile var skipped = 0; private set
    @Volatile var errors = 0; private set
    @Volatile var status = "대기 중"; private set
    @Volatile var lastSummary = ""; private set
    @Volatile var lastOk = true; private set
    @Volatile var queued = 0; private set

    fun addListener(l: () -> Unit) = listeners.add(l)
    fun removeListener(l: () -> Unit) = listeners.remove(l)

    fun logText(maxLines: Int = 120): String = synchronized(log) { log.takeLast(maxLines).joinToString("\n") }

    @Synchronized
    fun setQueued(count: Int) {
        queued = count
        changed()
    }

    /** 서비스가 요청을 받은 직후. 엔진 준비(첫 실행 땐 몇 초) 동안에도 '진행 중'으로 보이게 한다. */
    @Synchronized
    fun preparing() {
        if (!running) {
            running = true
            stopping = false
            status = "준비 중… (처음에는 엔진을 여느라 몇 초 걸립니다)"
        }
        changed()
    }

    /** 화면 갱신만 요청 (엔진 작업 결과 등). */
    fun touch() = changed()

    @Synchronized
    fun begin(targetLabel: String) {
        running = true
        stopping = false
        target = targetLabel
        downloaded = 0
        skipped = 0
        errors = 0
        status = "받는 중: $targetLabel"
        appendLog("---- $targetLabel ----")
        changed()
    }

    @Synchronized
    fun stopRequested() {
        if (running) {
            stopping = true
            status = "중지하는 중…"
            changed()
        }
    }

    /** 파이썬에서 오는 이벤트. kind: file / skip / error / warning / info */
    fun event(kind: String, text: String) {
        synchronized(this) {
            when (kind) {
                "file" -> downloaded++
                "skip" -> skipped++
                "error" -> errors++
            }
            if (running && !stopping) {
                status = "받는 중: $target — 받음 $downloaded · 건너뜀 $skipped" + if (errors > 0) " · 오류 $errors" else ""
            }
        }
        val prefix = when (kind) {
            "file" -> "✓ "
            "skip" -> "· (이미 받음) "
            "error" -> "⚠ "
            "warning" -> "! "
            else -> ""
        }
        appendLog(prefix + text)
        changed()
    }

    @Synchronized
    fun finishRun(summary: String, ok: Boolean) {
        lastSummary = summary
        lastOk = ok
        status = summary
        appendLog(summary)
        changed()
    }

    @Synchronized
    fun idle() {
        running = false
        stopping = false
        changed()
    }

    fun note(text: String) {
        appendLog(text)
        changed()
    }

    private fun appendLog(line: String) {
        synchronized(log) {
            log.addLast(line)
            while (log.size > MAX_LOG_LINES) log.removeFirst()
        }
    }

    /** 수천 개의 '건너뜀' 이벤트가 와도 화면 갱신은 0.15초에 한 번만. */
    private fun changed() {
        if (notifyPending) return
        notifyPending = true
        main.postDelayed({
            notifyPending = false
            listeners.forEach { it() }
        }, NOTIFY_DELAY_MS)
    }
}
