package io.github.xmedia.downloader

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Process

/**
 * 앱을 다시 시작한다 (엔진 업데이트 적용용). 이미 불러온 파이썬 모듈은 바꿀 수 없어서 프로세스를 새로 띄워야 한다.
 * 별도 프로세스(:restart)에서 원래 프로세스를 끝내고 첫 화면을 다시 연다 (ProcessPhoenix 방식).
 */
class RestartActivity : Activity() {
    companion object {
        private const val EXTRA_PID = "main_pid"

        fun restart(activity: Activity) {
            val intent = Intent(activity, RestartActivity::class.java)
                .putExtra(EXTRA_PID, Process.myPid())
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            activity.finish()
            Runtime.getRuntime().exit(0)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val mainPid = intent.getIntExtra(EXTRA_PID, -1)
        if (mainPid > 0 && mainPid != Process.myPid()) Process.killProcess(mainPid)
        startActivity(
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        )
        finish()
        Runtime.getRuntime().exit(0)
    }
}
