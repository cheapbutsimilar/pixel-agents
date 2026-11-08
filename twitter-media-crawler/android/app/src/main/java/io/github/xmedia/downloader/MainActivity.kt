package io.github.xmedia.downloader

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.PyException
import io.github.xmedia.downloader.databinding.ActivityMainBinding
import kotlin.system.exitProcess

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var settings: Settings
    private val main = Handler(Looper.getMainLooper())
    private val stateListener: () -> Unit = { render() }
    @Volatile private var engineBusy = false

    private val loginLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        renderLogin()
    }
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) {}

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        settings = Settings(this)

        loadForm()
        binding.rgTarget.setOnCheckedChangeListener { _, _ -> renderTargetMode() }
        binding.btnLogin.setOnClickListener { loginLauncher.launch(Intent(this, LoginActivity::class.java)) }
        binding.btnRelogin.setOnClickListener { confirmRelogin() }
        binding.btnManual.setOnClickListener { showManualLogin() }
        binding.btnStart.setOnClickListener { startDownload() }
        binding.btnStop.setOnClickListener { DownloadService.stop(this) }
        binding.btnEngineUpdate.setOnClickListener { updateEngine() }
        binding.btnEngineReset.setOnClickListener { resetEngine() }

        askNotificationPermissionOnce()
        loadEngineVersion()
    }

    override fun onStart() {
        super.onStart()
        DownloadState.addListener(stateListener)
        renderLogin()
        render()
    }

    override fun onStop() {
        DownloadState.removeListener(stateListener)
        saveForm()
        super.onStop()
    }

    // --- 입력 폼 ---

    private fun loadForm() {
        binding.rgTarget.check(if (settings.bookmarksMode) R.id.rbBookmarks else R.id.rbAccount)
        binding.etAccount.setText(settings.account)
        binding.rgMedia.check(
            when (settings.media) {
                "photos" -> R.id.rbPhotos
                "videos" -> R.id.rbVideos
                else -> R.id.rbAll
            }
        )
        binding.cbRetweets.isChecked = settings.retweets
        binding.cbQuick.isChecked = settings.quickRefresh
        renderTargetMode()
    }

    private fun saveForm() {
        settings.bookmarksMode = binding.rbBookmarks.isChecked
        settings.account = binding.etAccount.text?.toString()?.trim().orEmpty()
        settings.media = when (binding.rgMedia.checkedRadioButtonId) {
            R.id.rbPhotos -> "photos"
            R.id.rbVideos -> "videos"
            else -> "all"
        }
        settings.retweets = binding.cbRetweets.isChecked
        settings.quickRefresh = binding.cbQuick.isChecked
    }

    private fun renderTargetMode() {
        val account = binding.rbAccount.isChecked
        binding.tilAccount.isEnabled = account
        binding.cbRetweets.isEnabled = account
    }

    // --- 로그인 ---

    private fun renderLogin() {
        val login = XLogin.current(this)
        binding.tvLogin.text = when {
            login == null -> "로그인 안 됨 — 'X 로그인'을 눌러 X 계정으로 로그인하세요"
            login.manual -> "로그인됨 (직접 입력한 쿠키)"
            else -> "로그인됨"
        }
        binding.btnLogin.isEnabled = login == null
        binding.btnRelogin.isEnabled = login != null
    }

    private fun confirmRelogin() {
        AlertDialog.Builder(this)
            .setTitle("다시 로그인")
            .setMessage("저장된 X 로그인 정보를 지우고 다시 로그인합니다. 로그인 오류가 나거나 다른 계정을 쓰고 싶을 때 쓰세요.")
            .setPositiveButton("다시 로그인") { _, _ ->
                XLogin.logout(this)
                renderLogin()
                loginLauncher.launch(Intent(this, LoginActivity::class.java))
            }
            .setNegativeButton("취소", null)
            .show()
    }

    private fun showManualLogin() {
        val pad = (16 * resources.displayMetrics.density).toInt()
        val token = EditText(this).apply {
            hint = "auth_token"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        }
        val ct0 = EditText(this).apply {
            hint = "ct0 (권장)"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        }
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad / 2, pad, 0)
            addView(token)
            addView(ct0)
        }
        AlertDialog.Builder(this)
            .setTitle("쿠키 직접 입력")
            .setMessage("앱 안 로그인이 안 될 때만 쓰세요. PC 브라우저에서 x.com 로그인 → F12 → Application → Cookies 에서 두 값을 복사합니다.")
            .setView(box)
            .setPositiveButton("저장") { _, _ ->
                val t = Pure.cleanCookieValue(token.text.toString(), "auth_token")
                val c = Pure.cleanCookieValue(ct0.text.toString(), "ct0")
                if (t.isEmpty()) {
                    Toast.makeText(this, "auth_token을 입력하세요", Toast.LENGTH_LONG).show()
                    return@setPositiveButton
                }
                settings.saveLogin(Settings.Login(t, c, manual = true))
                if (!Pure.looksLikeAuthToken(t)) {
                    Toast.makeText(
                        this,
                        "auth_token 값이 이상합니다 (보통 40자리 영문·숫자인데 ${t.length}자리). 다시 확인하세요.",
                        Toast.LENGTH_LONG,
                    ).show()
                }
                renderLogin()
            }
            .setNegativeButton("취소", null)
            .show()
    }

    // --- 다운로드 ---

    private fun startDownload() {
        saveForm()
        if (XLogin.current(this) == null) {
            Toast.makeText(this, "먼저 X 로그인을 해 주세요", Toast.LENGTH_LONG).show()
            loginLauncher.launch(Intent(this, LoginActivity::class.java))
            return
        }
        val target = if (settings.bookmarksMode) "bookmarks" else settings.account
        if (target.isBlank()) {
            binding.tilAccount.error = "계정 아이디나 링크를 입력하세요"
            return
        }
        binding.tilAccount.error = null
        DownloadService.start(this, target)
    }

    private fun render() {
        val running = DownloadState.running
        binding.btnStart.isEnabled = !running
        binding.btnStop.isEnabled = running && !DownloadState.stopping
        binding.btnEngineUpdate.isEnabled = !running && !engineBusy
        binding.btnEngineReset.isEnabled = !running && !engineBusy
        val queued = DownloadState.queued
        binding.tvStatus.text = DownloadState.status + if (running && queued > 0) " (대기 ${queued}개)" else ""
        binding.tvLog.text = DownloadState.logText().ifEmpty { "아직 기록이 없습니다" }
    }

    private fun askNotificationPermissionOnce() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU || settings.askedNotificationPermission) return
        settings.askedNotificationPermission = true
        notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    // --- 엔진 ---

    private fun loadEngineVersion() {
        binding.tvEngine.text = "엔진: 준비 중…"
        Thread {
            val text = try {
                "엔진: gallery-dl " + Engine.bridge(applicationContext).callAttr("engine_version").toString()
            } catch (e: Exception) {
                "엔진을 불러오지 못했습니다: ${Pure.pythonErrorMessage(e.message)}"
            }
            main.post { if (!isDestroyed) binding.tvEngine.text = text }
        }.start()
    }

    private fun runEngineTask(busyText: String, call: String) {
        engineBusy = true
        render()
        binding.tvEngine.text = busyText
        Thread {
            val (ok, message) = try {
                true to Engine.bridge(applicationContext).callAttr(call).toString()
            } catch (e: PyException) {
                false to "실패: ${Pure.pythonErrorMessage(e.message)}"
            } catch (e: Exception) {
                false to "실패: ${e.message}"
            }
            main.post {
                engineBusy = false
                if (isDestroyed) return@post
                render()
                loadEngineVersion()
                val needsRestart = ok && message.contains("다시 시작")
                val dialog = AlertDialog.Builder(this).setMessage(message)
                if (needsRestart) {
                    dialog.setPositiveButton("지금 다시 시작") { _, _ -> restartApp() }
                    dialog.setNegativeButton("나중에", null)
                } else {
                    dialog.setPositiveButton("확인", null)
                }
                dialog.show()
            }
        }.start()
    }

    private fun updateEngine() = runEngineTask("엔진: 최신 버전 확인 중…", "update_engine")

    private fun resetEngine() {
        AlertDialog.Builder(this)
            .setMessage("업데이트한 엔진을 지우고 앱에 들어 있는 기본 엔진으로 되돌릴까요? 업데이트 후 오히려 안 될 때 쓰세요.")
            .setPositiveButton("되돌리기") { _, _ -> runEngineTask("엔진: 되돌리는 중…", "reset_engine") }
            .setNegativeButton("취소", null)
            .show()
    }

    /** 이미 불러온 파이썬 모듈은 바꿀 수 없으므로, 새 엔진을 쓰려면 앱 프로세스를 다시 시작한다. */
    private fun restartApp() {
        if (DownloadState.running) {
            Toast.makeText(this, "다운로드가 끝난 뒤에 다시 시작하세요", Toast.LENGTH_LONG).show()
            return
        }
        val intent = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        startActivity(intent)
        exitProcess(0)
    }
}
