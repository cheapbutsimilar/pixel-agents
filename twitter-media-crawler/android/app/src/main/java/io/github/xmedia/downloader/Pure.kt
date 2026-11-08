package io.github.xmedia.downloader

import java.io.File

/** 안드로이드 API에 의존하지 않는 순수 함수들 (JVM 단위 테스트 대상). */
object Pure {
    /** 갤러리(사진 앱)에 보이는 저장 위치: Pictures/XMedia/<폴더> */
    const val ALBUM_ROOT = "XMedia"

    /** 받은 기록 등 앱 내부용 폴더. 사진 앱으로 옮기지 않는다. */
    const val HISTORY_DIR = ".download-history"

    /** "a=1; b=2" 형태의 쿠키 헤더를 이름→값으로. */
    fun parseCookieHeader(header: String?): Map<String, String> =
        header.orEmpty()
            .split(';')
            .mapNotNull { part ->
                val eq = part.indexOf('=')
                if (eq <= 0) null else part.substring(0, eq).trim() to part.substring(eq + 1).trim()
            }
            .filter { it.first.isNotEmpty() }
            .toMap()

    /** 복사·붙여넣기 실수(따옴표, "auth_token=" 접두어, 공백, 세미콜론)를 정리한다. PC 버전 clean_cookie_value와 같음. */
    fun cleanCookieValue(value: String, name: String): String {
        var v = value.trim().trim('"', '\'').trim()
        if (v.startsWith("$name=")) v = v.substring(name.length + 1).trim()
        return v.trimEnd(';').trim()
    }

    /** auth_token은 보통 영문 소문자·숫자 40자리. 다르면 다른 값을 복사했을 가능성이 높다. */
    fun looksLikeAuthToken(value: String): Boolean = Regex("[0-9a-f]{40}").matches(value)

    fun mimeTypeFor(fileName: String): String =
        when (fileName.substringAfterLast('.', "").lowercase()) {
            "jpg", "jpeg" -> "image/jpeg"
            "png" -> "image/png"
            "webp" -> "image/webp"
            "gif" -> "image/gif"
            "mp4", "m4v" -> "video/mp4"
            "mov" -> "video/quicktime"
            "webm" -> "video/webm"
            else -> "application/octet-stream"
        }

    /** MediaStore RELATIVE_PATH. 사진·동영상은 Pictures, 그 밖의 파일은 Download 아래에 둔다. */
    fun relativePathFor(mime: String, folder: String): String {
        val top = if (mime.startsWith("image/") || mime.startsWith("video/")) "Pictures" else "Download"
        val safeFolder = sanitizeFolder(folder)
        return if (safeFolder.isEmpty()) "$top/$ALBUM_ROOT" else "$top/$ALBUM_ROOT/$safeFolder"
    }

    /** 폴더 이름에 경로 구분자나 상위 경로가 끼어들지 않게 한다 (계정 아이디는 원래 영문·숫자·_ 뿐). */
    fun sanitizeFolder(folder: String): String =
        folder.replace(Regex("[^A-Za-z0-9_.-]"), "_").trim('.').take(60)

    /** 다운로드 중이거나 앱 내부용이라 아직 옮기면 안 되는 파일인지. */
    fun isPublishable(file: File): Boolean {
        val name = file.name
        return file.isFile && !name.endsWith(".part") && !name.startsWith(".") && !name.endsWith(".tmp")
    }

    /**
     * 스테이징 폴더에 남아 있는(이전에 사진 앱으로 옮기지 못한) 파일과 그 폴더 이름.
     * staging/<폴더>/<파일> 구조이며, 받은 기록 폴더는 제외한다.
     */
    fun leftoverFiles(staging: File): List<Pair<File, String>> {
        if (!staging.isDirectory) return emptyList()
        return staging.walkTopDown()
            .onEnter { it == staging || it.name != HISTORY_DIR }
            .filter { it != staging && isPublishable(it) }
            .map { file ->
                val rel = file.relativeTo(staging).invariantSeparatorsPath
                file to (if ('/' in rel) rel.substringBefore('/') else "")
            }
            .sortedBy { it.first.path }
            .toList()
    }

    /** 파이썬 예외 메시지 "ValueError: 설명" → "설명" */
    fun pythonErrorMessage(message: String?): String {
        val text = message.orEmpty().lineSequence().firstOrNull { it.isNotBlank() }.orEmpty().trim()
        return text.replace(Regex("^[A-Za-z_.]*(Error|Exception): "), "").ifEmpty { "알 수 없는 오류" }
    }
}
