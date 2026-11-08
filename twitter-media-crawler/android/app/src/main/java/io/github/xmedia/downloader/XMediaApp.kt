package io.github.xmedia.downloader

import android.app.Application

class XMediaApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Notifications.createChannels(this)
    }
}
