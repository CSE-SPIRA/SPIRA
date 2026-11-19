package org.cse_spira.spira_app

import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.util.AtomicFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.UUID

/** All access is serialized on the process-wide share worker. */
internal class ShareInbox(private val context: Context) {
    private val root = File(context.noBackupFilesDir, "order-shares-v1")
    private val preferences = context.getSharedPreferences("spira-share-inbox", Context.MODE_PRIVATE)

    fun receive(intent: Intent) {
        val receivedAt = System.currentTimeMillis()
        try {
            val images = sharedUris(intent)
            if (images.size !in 1..3) throw InvalidShare("count")
            if (!root.exists() && !root.mkdirs()) error("Inbox unavailable")
            val staging = File(root, ".copy-${UUID.randomUUID()}")
            check(staging.mkdir())
            try {
                val digest = MessageDigest.getInstance("SHA-256")
                val names = images.mapIndexed { index, uri -> copyImage(uri, index, staging, digest) }
                val sourceId = "android_${digest.digest().hex()}"
                val record = File(root, sourceId)
                if (!record.exists()) {
                    val sharedAt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.ROOT)
                        .apply { timeZone = TimeZone.getTimeZone("UTC") }.format(Date(receivedAt))
                    write(File(staging, "order"), JSONObject()
                        .put("sharedAt", sharedAt)
                        .put("receivedAt", receivedAt)
                        .put("images", JSONArray(names)).toString())
                    check(staging.renameTo(record))
                }
            } finally {
                staging.deleteRecursively()
            }
            preferences.edit().remove("issue").apply()
        } catch (error: InvalidShare) {
            preferences.edit().putString("issue", error.kind).apply()
        } catch (_: Exception) {
            preferences.edit().putString("issue", "unavailable").apply()
        }
    }

    fun list(scope: String): Map<String, Any?> {
        val orders = root.listFiles().orEmpty().mapNotNull { record ->
            if (record.name.startsWith(".copy-")) {
                record.deleteRecursively()
                return@mapNotNull null
            }
            if (!record.isDirectory || !record.name.startsWith("android_")) return@mapNotNull null
            val order = JSONObject(read(File(record, "order")))
            val resolved = File(record, "resolved")
            val images = order.getJSONArray("images")
            val paths = (0 until images.length()).map { File(record, images.getString(it)) }
            if (resolved.exists()) {
                paths.forEach { it.delete() }
                return@mapNotNull null
            }
            val owner = File(record, "scope")
            if (!owner.exists()) write(owner, scope)
            if (read(owner) != scope) return@mapNotNull null
            order.getLong("receivedAt") to mapOf(
                "sourceId" to record.name,
                "sharedAt" to order.getString("sharedAt"),
                "images" to paths.map { it.absolutePath },
            )
        }.sortedBy { it.first }.map { it.second }
        return mapOf("orders" to orders, "issue" to preferences.getString("issue", null))
    }

    fun acknowledge(scope: String, sourceId: String, episodeId: String) =
        resolve(scope, sourceId, episodeId)

    fun discardInvalid(scope: String, sourceId: String) {
        resolve(scope, sourceId, "invalid_image")
        preferences.edit().putString("issue", "rejected").apply()
    }

    private fun resolve(scope: String, sourceId: String, outcome: String) {
        require(sourceId.matches(Regex("android_[a-f0-9]{64}")))
        val record = File(root, sourceId)
        check(read(File(record, "scope")) == scope)
        // Save the outcome before deleting image bytes. The marker suppresses redelivery.
        write(File(record, "resolved"), outcome)
        val images = JSONObject(read(File(record, "order"))).getJSONArray("images")
        for (index in 0 until images.length()) File(record, images.getString(index)).delete()
    }

    @Suppress("DEPRECATION")
    private fun sharedUris(intent: Intent): List<Uri> {
        val streams = if (intent.action == Intent.ACTION_SEND_MULTIPLE)
            intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty()
        else listOfNotNull(intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))
        if (streams.isNotEmpty()) return streams
        val clip = intent.clipData ?: return emptyList()
        return (0 until clip.itemCount).map { clip.getItemAt(it).uri ?: throw InvalidShare("format") }
    }

    private fun copyImage(uri: Uri, index: Int, staging: File, digest: MessageDigest): String {
        if (uri.scheme != "content") throw InvalidShare("format")
        val file = File(staging, "$index.tmp")
        val contentDigest = MessageDigest.getInstance("SHA-256")
        val input = context.contentResolver.openInputStream(uri) ?: throw InvalidShare("unavailable")
        input.use { source ->
            FileOutputStream(file).use { target ->
                val buffer = ByteArray(16 * 1024)
                var total = 0
                while (true) {
                    val count = source.read(buffer)
                    if (count == -1) break
                    total += count
                    if (total > maxImageBytes) throw InvalidShare("size")
                    contentDigest.update(buffer, 0, count)
                    target.write(buffer, 0, count)
                }
                target.fd.sync()
            }
        }

        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        val extension = when (bounds.outMimeType) {
            "image/png" -> "png"
            "image/jpeg" -> "jpg"
            else -> throw InvalidShare("format")
        }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) throw InvalidShare("format")
        val options = BitmapFactory.Options().apply {
            inSampleSize = 1
            val longest = maxOf(bounds.outWidth, bounds.outHeight)
            while (longest / inSampleSize > 512) inSampleSize *= 2
        }
        val decoded = BitmapFactory.decodeFile(file.path, options) ?: throw InvalidShare("format")
        decoded.recycle()

        // Android SEND has no delivery ID. The ordered URI and content pairs are
        // stable across redelivery and distinguish new captures at new URIs.
        digest.update(uri.toString().toByteArray(Charsets.UTF_8))
        digest.update(0)
        digest.update(contentDigest.digest())
        val name = "$index.$extension"
        check(file.renameTo(File(staging, name)))
        return name
    }

    private fun write(file: File, value: String) {
        val atomic = AtomicFile(file)
        val stream = atomic.startWrite()
        try {
            stream.write(value.toByteArray(Charsets.UTF_8))
            atomic.finishWrite(stream)
        } catch (error: Exception) {
            atomic.failWrite(stream)
            throw error
        }
    }

    private fun read(file: File): String = AtomicFile(file).readFully().toString(Charsets.UTF_8)

    private class InvalidShare(val kind: String) : Exception()

    companion object {
        private const val maxImageBytes = 5 * 1024 * 1024

        fun hash(value: String): String =
            MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).hex()

        private fun ByteArray.hex() = joinToString("") { "%02x".format(it) }
    }
}
