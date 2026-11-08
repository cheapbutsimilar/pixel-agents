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
            module.callAttr("init", app.filesDir.absolutePath)
            bridge = module
            return module
        }
    }

    fun stagingDir(context: Context): File = File(context.applicationContext.filesDir, "staging").apply { mkdirs() }
}
