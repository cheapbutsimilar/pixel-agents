package io.github.xmedia.downloader

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import io.github.xmedia.downloader.databinding.ActivityLoginBinding

/**
 * 앱 안에서 X에 로그인한다. 로그인이 끝나면 WebView 쿠키에서 auth_token/ct0를 읽어 저장하고 닫힌다.
 * 비밀번호는 X 로그인 페이지에 직접 입력되며 이 앱은 비밀번호를 보거나 저장하지 않는다.
 */
class LoginActivity : AppCompatActivity() {
    companion object {
        private const val LOGIN_URL = "https://x.com/i/flow/login"
        private const val POLL_MS = 1000L
        private const val SETTLE_MS = 1500L
    }

    private lateinit var binding: ActivityLoginBinding
    private val handler = Handler(Looper.getMainLooper())
    private var done = false

    private val poll = object : Runnable {
        override fun run() {
            if (checkLoggedIn()) return
            handler.postDelayed(this, POLL_MS)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)
        title = "X 로그인"

        val web = binding.webView
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
        web.settings.apply {
            javaScriptEnabled = true // X 로그인 페이지는 자바스크립트가 필요하다
            domStorageEnabled = true
            // 일부 사이트는 앱 내장 브라우저 표시("; wv")를 보고 로그인을 막는다
            userAgentString = userAgentString.replace("; wv", "")
        }
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean = false

            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                binding.progress.visibility = View.VISIBLE
            }

            override fun onPageFinished(view: WebView, url: String?) {
                binding.progress.visibility = View.GONE
                checkLoggedIn()
            }
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
            }
        })

        if (!checkLoggedIn()) web.loadUrl(LOGIN_URL)
    }

    override fun onResume() {
        super.onResume()
        if (!done) handler.postDelayed(poll, POLL_MS)
    }

    override fun onPause() {
        handler.removeCallbacks(poll)
        super.onPause()
    }

    override fun onDestroy() {
        handler.removeCallbacks(poll)
        binding.webView.destroy()
        super.onDestroy()
    }

    /**
     * 로그인 쿠키가 생겼으면 저장하고 닫는다.
     * auth_token이 먼저 오고 짝이 되는 새 ct0가 조금 뒤에 오는 경우가 있어, 잠깐 기다렸다가 다시 읽어 저장한다.
     */
    private fun checkLoggedIn(): Boolean {
        if (done) return true
        val first = XLogin.fromWebView() ?: return false
        done = true
        handler.removeCallbacks(poll)
        binding.progress.visibility = View.VISIBLE
        handler.postDelayed({
            if (isFinishing || isDestroyed) return@postDelayed
            val login = XLogin.fromWebView() ?: first
            CookieManager.getInstance().flush()
            Settings(this).saveLogin(login)
            Toast.makeText(this, "X 로그인 완료", Toast.LENGTH_SHORT).show()
            setResult(RESULT_OK)
            finish()
        }, SETTLE_MS)
        return true
    }
}
