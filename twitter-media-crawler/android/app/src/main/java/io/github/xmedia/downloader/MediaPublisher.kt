package io.github.xmedia.downloader

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import java.io.File
import java.io.IOException

/**
 * 앱 내부(스테이징)에 받은 파일을 사진 앱(MediaStore)으로 옮긴다.
 * 저장소 권한 없이 동작하고, 앱을 지워도 사진은 남는다. 위치: Pictures/XMedia/<북마크 또는 계정>
 */
object MediaPublisher {
    /** 성공하면 스테이징 파일을 지우고 Uri를 돌려준다. 실패하면 IOException (스테이징 파일은 남겨 다음에 다시 시도). */
    @Throws(IOException::class)
    fun publish(context: Context, file: File, folder: String): Uri {
        if (!file.isFile) throw IOException("파일이 없습니다: ${file.name}")
        val mime = Pure.mimeTypeFor(file.name)
        val collection = when {
            mime.startsWith("image/") -> MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            mime.startsWith("video/") -> MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
            else -> MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        }
        val resolver = context.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, file.name)
            put(MediaStore.MediaColumns.MIME_TYPE, mime)
            put(MediaStore.MediaColumns.RELATIVE_PATH, Pure.relativePathFor(mime, folder, Build.VERSION.SDK_INT))
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val uri = try {
            resolver.insert(collection, values)
        } catch (e: Exception) { // 허용되지 않는 폴더 등은 IllegalArgumentException으로 온다
            throw IOException(e.message ?: e.javaClass.simpleName, e)
        } ?: throw IOException("사진 앱에 항목을 만들지 못했습니다")
        try {
            val out = resolver.openOutputStream(uri) ?: throw IOException("사진 앱 파일을 열지 못했습니다")
            out.use { stream -> file.inputStream().use { it.copyTo(stream) } }
            val done = ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) }
            resolver.update(uri, done, null, null)
        } catch (e: Exception) {
            try {
                resolver.delete(uri, null, null)
            } catch (_: Exception) {
            }
            throw if (e is IOException) e else IOException(e.message ?: e.javaClass.simpleName, e)
        }
        file.delete()
        return uri
    }

    /** 지난번에 옮기지 못하고 남은 파일들을 다시 옮긴다. 옮긴 개수를 돌려준다. */
    fun publishLeftovers(context: Context, staging: File, onError: (File, Exception) -> Unit = { _, _ -> }): Int {
        var count = 0
        for ((file, folder) in Pure.leftoverFiles(staging)) {
            try {
                publish(context, file, folder)
                count++
            } catch (e: Exception) {
                onError(file, e)
            }
        }
        return count
    }
}
