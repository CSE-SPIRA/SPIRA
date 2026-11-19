package org.cse_spira.spira_app

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    private val inbox by lazy { ShareInbox(applicationContext) }
    private var channel: MethodChannel? = null
    private val notifications by lazy { getSystemService(NotificationManager::class.java) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        receive(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        receive(intent)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "spira/app").apply {
            setMethodCallHandler { call, result ->
                when (call.method) {
                    "inbox" -> onWorker(result) { inbox.list(call.arguments as String) }
                    "acknowledge" -> onWorker(result) {
                        inbox.acknowledge(
                            call.argument<String>("scope")!!,
                            call.argument<String>("sourceId")!!,
                            call.argument<String>("episodeId")!!,
                        )
                        null
                    }
                    "discardInvalid" -> onWorker(result) {
                        inbox.discardInvalid(
                            call.argument<String>("scope")!!,
                            call.argument<String>("sourceId")!!,
                        )
                        null
                    }
                    "notify" -> onWorker(result) {
                        notifyOnce(
                            call.argument<String>("scope")!!,
                            call.argument<String>("key")!!,
                            call.argument<String>("title")!!,
                            call.argument<String>("text")!!,
                        )
                    }
                    "requestNotificationPermission" -> {
                        val permissions = getSharedPreferences("spira-permissions", MODE_PRIVATE)
                        if (Build.VERSION.SDK_INT >= 33 &&
                            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
                            !permissions.getBoolean("notifications_requested", false)
                        ) {
                            permissions.edit().putBoolean("notifications_requested", true).apply()
                            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
                        }
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            }
        }
    }

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        channel?.setMethodCallHandler(null)
        channel = null
        super.cleanUpFlutterEngine(flutterEngine)
    }

    private fun receive(share: Intent?) {
        if (share == null || (share.action != Intent.ACTION_SEND && share.action != Intent.ACTION_SEND_MULTIPLE)) return
        worker.execute {
            inbox.receive(share)
            runOnUiThread {
                if (intent === share) setIntent(Intent(this, MainActivity::class.java))
                channel?.invokeMethod("sharesChanged", null)
            }
        }
    }

    private fun onWorker(result: MethodChannel.Result, operation: () -> Any?) {
        worker.execute {
            try {
                result.success(operation())
            } catch (_: Exception) {
                result.error("storage_unavailable", null, null)
            }
        }
    }

    private fun notifyOnce(scope: String, key: String, title: String, text: String): Boolean {
        val tag = ShareInbox.hash("$scope\u0000$key")
        val ledger = getSharedPreferences("spira-notifications", MODE_PRIVATE)
        if (ledger.getBoolean(tag, false)) return true
        if (!notifications.areNotificationsEnabled()) return false
        if (Build.VERSION.SDK_INT >= 26) {
            notifications.createNotificationChannel(
                NotificationChannel(channelId, "준비 알림", NotificationManager.IMPORTANCE_DEFAULT)
            )
            if (notifications.getNotificationChannel(channelId).importance == NotificationManager.IMPORTANCE_NONE) {
                return false
            }
        }
        val launch = Intent(this, MainActivity::class.java).setAction(Intent.ACTION_MAIN)
        val pending = PendingIntent.getActivity(this, 0, launch, PendingIntent.FLAG_IMMUTABLE)
        @Suppress("DEPRECATION")
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, channelId)
            else Notification.Builder(this)
        val notification = builder.setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(pending)
            .setOnlyAlertOnce(true)
            .setAutoCancel(true)
            .build()
        // Reserve the delivery before posting so a process restart cannot alert twice.
        if (!ledger.edit().putBoolean(tag, true).commit()) return false
        try {
            notifications.notify(tag, 1, notification)
        } catch (error: Exception) {
            ledger.edit().remove(tag).commit()
            throw error
        }
        return true
    }

    companion object {
        private const val channelId = "spira_preparations"
        private val worker = Executors.newSingleThreadExecutor()
    }
}
