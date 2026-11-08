package io.github.xmedia.downloader

import android.content.Context
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

/**
 * 파이썬 다운로드 엔진(android_bridge.py + gallery-dl).
 * 처음 시작할 때 몇 초 걸릴 수 있으므로 반드시 백그라운드 스레드에서 부른다.
 */
object Engine {
    @Volatile private var bridge: PyObject? = null

    fun bridge(context: Context): PyObject {
        bridge?.let { return it }
        synchronized(this) {
            bridge?.let { return it }
            val app = context.applicationContext
            if (!Python.isStarted()) Python.start(AndroidPlatform(app))
            val module = Python.getInstance().getModule("android_bridge")
            // gallery_dl을 import하기 전에 불러야 '엔진 업데이트'로 받은 버전이 적용된다
            module.callAttr("init", app.filesDir.absolutePath, BuildConfig.GALLERY_DL_VERSION)
            bridge = module
            return module
        }
    }

    fun stagingDir(context: Context): File = File(context.applicationContext.filesDir, "staging").apply { mkdirs() }
}

/**
 * 엔진 업데이트/되돌리기 작업. 화면 회전 등으로 화면이 다시 만들어져도 진행 상태와 결과가 남도록
 * 화면(Activity)이 아니라 프로세스에 둔다.
 */
object EngineTasks {
    data class Result(val message: String, val restart: Boolean)

    @Volatile var busy = false; private set
    @Volatile var busyText = ""; private set
    private var pending: Result? = null

    /** 아직 보여주지 않은 결과를 꺼낸다 (한 번만). */
    @Synchronized
    fun takeResult(): Result? = pending.also { pending = null }

    /** call: android_bridge의 update_engine 또는 reset_engine. 이미 진행 중이면 false. */
    fun start(context: Context, text: String, call: String): Boolean {
        synchronized(this) {
            if (busy) return false
            busy = true
            busyText = text
        }
        DownloadState.touch()
        val app = context.applicationContext
        Thread({
            val result = try {
                val json = org.json.JSONObject(Engine.bridge(app).callAttr(call).toString())
                Result(json.optString("message"), json.optBoolean("restart"))
            } catch (e: com.chaquo.python.PyException) {
                Result("실패: ${Pure.pythonErrorMessage(e.message)}", false)
            } catch (e: Exception) {
                Result("실패: ${e.message ?: e.javaClass.simpleName}", false)
            }
            synchronized(this) {
                pending = result
                busy = false
            }
            DownloadState.touch()
        }, "xmedia-engine").start()
        return true
    }
}
