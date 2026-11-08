package io.github.xmedia.downloader

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class PureTest {
    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun parsesCookieHeader() {
        val c = Pure.parseCookieHeader("guest_id=v1%3A1; auth_token=abc; ct0=def ; lang=ko; broken; =x")
        assertEquals("abc", c["auth_token"])
        assertEquals("def", c["ct0"])
        assertEquals("v1%3A1", c["guest_id"])
        assertFalse(c.containsKey(""))
        assertTrue(Pure.parseCookieHeader(null).isEmpty())
        assertTrue(Pure.parseCookieHeader("").isEmpty())
    }

    @Test
    fun cleansPastedCookieValues() {
        assertEquals("abc", Pure.cleanCookieValue("  \"abc\" ", "auth_token"))
        assertEquals("abc", Pure.cleanCookieValue("auth_token=abc;", "auth_token"))
        assertEquals("xyz", Pure.cleanCookieValue("ct0= xyz ", "ct0"))
        assertEquals("", Pure.cleanCookieValue("   ", "ct0"))
    }

    @Test
    fun authTokenFormat() {
        assertTrue(Pure.looksLikeAuthToken("0123456789abcdef0123456789abcdef01234567"))
        assertFalse(Pure.looksLikeAuthToken("auth_token"))
        assertFalse(Pure.looksLikeAuthToken("0123456789ABCDEF0123456789abcdef01234567"))
    }

    @Test
    fun mimeAndRelativePath() {
        assertEquals("image/jpeg", Pure.mimeTypeFor("20241026_alice_1_1.JPG"))
        assertEquals("video/mp4", Pure.mimeTypeFor("a.mp4"))
        assertEquals("application/octet-stream", Pure.mimeTypeFor("noext"))
        assertEquals("Pictures/XMedia/bookmarks", Pure.relativePathFor("image/jpeg", "bookmarks"))
        assertEquals("Pictures/XMedia/nasa", Pure.relativePathFor("video/mp4", "nasa"))
        assertEquals("Download/XMedia/nasa", Pure.relativePathFor("application/octet-stream", "nasa"))
        assertEquals("Pictures/XMedia", Pure.relativePathFor("image/png", ""))
        // 경로 조작 방지
        assertEquals("Pictures/XMedia/_.._evil", Pure.relativePathFor("image/png", "/../evil"))
        assertEquals("Pictures/XMedia", Pure.relativePathFor("image/png", ".."))
    }

    @Test
    fun findsLeftoverFilesButNotHistoryOrPartials() {
        val staging = tmp.newFolder("staging")
        fun touch(path: String) = File(staging, path).apply { parentFile!!.mkdirs(); writeText("x") }
        touch("bookmarks/a.jpg")
        touch("bookmarks/b.mp4.part")
        touch("nasa/c.mp4")
        touch(".download-history/bookmarks.sqlite3")
        touch(".download-history/bookmarks.json")
        touch("loose.jpg")
        val found = Pure.leftoverFiles(staging).map { it.first.relativeTo(staging).invariantSeparatorsPath to it.second }
        assertEquals(listOf("bookmarks/a.jpg" to "bookmarks", "loose.jpg" to "", "nasa/c.mp4" to "nasa"), found)
        assertTrue(Pure.leftoverFiles(File(staging, "missing")).isEmpty())
    }

    @Test
    fun pythonErrorMessages() {
        assertEquals("올바른 계정 아이디가 아닙니다: x y", Pure.pythonErrorMessage("ValueError: 올바른 계정 아이디가 아닙니다: x y"))
        assertEquals("boom", Pure.pythonErrorMessage("RuntimeError: boom\n  at ..."))
        assertEquals("plain", Pure.pythonErrorMessage("plain"))
        assertEquals("알 수 없는 오류", Pure.pythonErrorMessage(null))
    }
}
