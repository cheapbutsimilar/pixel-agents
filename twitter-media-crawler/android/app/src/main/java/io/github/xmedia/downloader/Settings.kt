package io.github.xmedia.downloader

import android.content.Context
import android.webkit.CookieManager

/** 앱 설정과 로그인 정보 (앱 전용 저장소, 다른 앱은 읽을 수 없다). */
class Settings(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var bookmarksMode: Boolean
        get() = prefs.getBoolean("bookmarks_mode", true)
        set(v) = prefs.edit().putBoolean("bookmarks_mode", v).apply()

    var account: String
        get() = prefs.getString("account", "").orEmpty()
        set(v) = prefs.edit().putString("account", v).apply()

    /** all / photos / videos (파이썬 MEDIA_* 와 같은 값) */
    var media: String
        get() = prefs.getString("media", "all").orEmpty()
        set(v) = prefs.edit().putString("media", v).apply()

    var retweets: Boolean
        get() = prefs.getBoolean("retweets", false)
        set(v) = prefs.edit().putBoolean("retweets", v).apply()

    var quickRefresh: Boolean
        get() = prefs.getBoolean("quick_refresh", true)
        set(v) = prefs.edit().putBoolean("quick_refresh", v).apply()

    var askedNotificationPermission: Boolean
        get() = prefs.getBoolean("asked_notification_permission", false)
        set(v) = prefs.edit().putBoolean("asked_notification_permission", v).apply()

    // --- 로그인 ---

    data class Login(val authToken: String, val ct0: String, val manual: Boolean)

    fun savedLogin(): Login? {
        val token = prefs.getString("auth_token", "").orEmpty()
        if (token.isEmpty()) return null
        return Login(token, prefs.getString("ct0", "").orEmpty(), prefs.getBoolean("login_manual", false))
    }

    fun saveLogin(login: Login) {
        prefs.edit()
            .putString("auth_token", login.authToken)
            .putString("ct0", login.ct0)
            .putBoolean("login_manual", login.manual)
            .apply()
    }

    fun clearLogin() {
        prefs.edit().remove("auth_token").remove("ct0").remove("login_manual").apply()
    }
}

/** X 로그인 쿠키를 앱 안의 웹 로그인(WebView) 또는 직접 입력한 값에서 가져온다. */
object XLogin {
    private const val X_URL = "https://x.com"

    /** WebView 쿠키 저장소에 있는 auth_token/ct0. 메인 스레드에서 부르는 것을 권장. */
    fun fromWebView(): Settings.Login? {
        val cookies = try {
            Pure.parseCookieHeader(CookieManager.getInstance().getCookie(X_URL))
        } catch (e: Exception) {
            return null // WebView가 설치되지 않았거나 초기화 실패
        }
        val token = cookies["auth_token"].orEmpty()
        if (token.isEmpty()) return null
        return Settings.Login(token, cookies["ct0"].orEmpty(), manual = false)
    }

    /**
     * 다운로드에 쓸 로그인. 직접 입력했으면 그 값을, 웹 로그인이면 WebView의 최신 쿠키를 쓴다
     * (X가 ct0를 바꾸는 경우가 있어 저장된 값보다 최신 값이 낫다).
     */
    fun current(context: Context): Settings.Login? {
        val settings = Settings(context)
        val saved = settings.savedLogin()
        if (saved?.manual == true) return saved
        val web = fromWebView()
        if (web != null) {
            if (web != saved) settings.saveLogin(web)
            return web
        }
        return saved
    }

    fun logout(context: Context) {
        Settings(context).clearLogin()
        try {
            CookieManager.getInstance().removeAllCookies(null)
            CookieManager.getInstance().flush()
        } catch (_: Exception) {
        }
    }
}
