package io.github.xmedia.downloader

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Toast

/**
 * X 앱 등에서 '공유 → X 미디어 다운로더'를 고르면 열리는 보이지 않는 화면.
 * 공유된 링크를 다운로드 서비스에 넘기고 바로 닫힌다. (게시물 링크 = 그 게시물, 프로필 링크 = 계정 전체)
 */
class ShareActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text = intent?.takeIf { it.action == Intent.ACTION_SEND }
            ?.getStringExtra(Intent.EXTRA_TEXT)
            ?.trim()
            .orEmpty()

        when {
            text.isEmpty() -> toast("공유된 링크가 없습니다")
            XLogin.current(this) == null -> {
                toast("먼저 앱에서 X 로그인을 해 주세요")
                startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
            else -> {
                DownloadService.start(this, text)
                toast("다운로드를 시작합니다. 진행 상황은 알림에서 볼 수 있어요")
            }
        }
        finish()
    }

    private fun toast(message: String) = Toast.makeText(applicationContext, message, Toast.LENGTH_LONG).show()
}
