package com.sessionchat

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.*
import org.json.JSONObject
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

private val http = OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS).build()
private data class GameResult(val name: String, val placeId: String)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { SessionChatApp() }
    }
}

@Composable
private fun SessionChatApp() {
    var server by remember { mutableStateOf("ws://10.0.2.2:8765") }
    var nickname by remember { mutableStateOf("Player") }
    var code by remember { mutableStateOf("") }
    var placeId by remember { mutableStateOf("") }
    var query by remember { mutableStateOf("") }
    var status by remember { mutableStateOf("Choose a room to join") }
    var activeRoom by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    val messages = remember { mutableStateListOf<String>() }
    val results = remember { mutableStateListOf<GameResult>() }
    var socket by remember { mutableStateOf<WebSocket?>(null) }
    val scope = rememberCoroutineScope()

    fun connect(payload: JSONObject, label: String) {
        socket?.close(1000, "Switching room")
        messages.clear()
        activeRoom = label
        status = "Connecting…"
        socket = http.newWebSocket(Request.Builder().url(server.trim()).build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    webSocket.send(payload.toString())
                    status = "Connected"
                }
                override fun onMessage(webSocket: WebSocket, text: String) {
                    try {
                        val packet = JSONObject(text)
                        when (packet.optString("type")) {
                            "message" -> messages.add(packet.optString("nickname") + ": " + packet.optString("text"))
                            "system" -> messages.add("• " + packet.optString("message"))
                            "status" -> status = packet.optString("message")
                            "error" -> status = packet.optString("message")
                        }
                    } catch (_: Exception) { }
                }
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    status = "Connection failed: " + (t.message ?: "check server URL")
                }
                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    if (activeRoom.isNotBlank()) status = "Disconnected"
                }
            })
    }

    fun joinCode() {
        val clean = code.filter(Char::isDigit)
        if (clean.length != 4) { status = "Enter the 4-digit room code"; return }
        connect(JSONObject().put("type", "join").put("room_code", clean)
            .put("nickname", nickname.take(20)), "Invite " + clean)
    }

    fun joinPlace(id: String) {
        if (id.isBlank() || !id.all(Char::isDigit)) { status = "Enter a numeric PlaceId"; return }
        connect(JSONObject().put("type", "join").put("place_id", id)
            .put("nickname", nickname.take(20)), "PlaceId " + id)
    }

    MaterialTheme(colorScheme = darkColorScheme(
        primary = Color(0xFF83B7FF), background = Color(0xFF10151E), surface = Color(0xFF1B2330)
    )) {
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                Text("SESSIONCHAT", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = Color(0xFFDCE7F7))
                Text(status, style = MaterialTheme.typography.bodySmall, color = Color(0xFF9AA9BD))
                OutlinedTextField(server, { server = it }, label = { Text("WebSocket server URL") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(nickname, { nickname = it.take(20) }, label = { Text("Nickname") }, singleLine = true, modifier = Modifier.fillMaxWidth())

                Text("Join a friend's PC room", color = Color.White, fontWeight = FontWeight.SemiBold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedTextField(code, { code = it.filter(Char::isDigit).take(4) },
                        label = { Text("4-digit code") }, singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f))
                    Button(onClick = { joinCode() }, modifier = Modifier.padding(top = 7.dp)) { Text("Join") }
                }

                HorizontalDivider(color = Color(0xFF30394A))
                Text("Find a game by name or PlaceId", color = Color.White, fontWeight = FontWeight.SemiBold)
                OutlinedTextField(query, { query = it }, label = { Text("Game name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Button(
                    onClick = {
                        scope.launch {
                            status = "Searching Roblox…"
                            try {
                                val found = withContext(Dispatchers.IO) {
                                    val encoded = URLEncoder.encode(query.trim(), "UTF-8")
                                    val response = URL("https://games.roblox.com/v1/games/search?keyword=" + encoded + "&limit=10").readText()
                                    val data = JSONObject(response).optJSONArray("data")
                                    buildList {
                                        if (data != null) for (i in 0 until data.length()) {
                                            val item = data.getJSONObject(i)
                                            val id = item.optLong("rootPlaceId")
                                            if (id > 0) add(GameResult(item.optString("name"), id.toString()))
                                        }
                                    }
                                }
                                results.clear()
                                results.addAll(found)
                                status = if (found.isEmpty()) "No games found" else "Tap a result to join its shared chat"
                            } catch (e: Exception) { status = "Search failed: " + (e.message ?: "network error") }
                        }
                    },
                    enabled = query.isNotBlank(), modifier = Modifier.fillMaxWidth()
                ) { Text("Search Roblox games") }

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedTextField(placeId, { placeId = it.filter(Char::isDigit) },
                        label = { Text("PlaceId") }, singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.weight(1f))
                    Button(onClick = { joinPlace(placeId) }, enabled = placeId.isNotBlank(),
                        modifier = Modifier.padding(top = 7.dp)) { Text("Join") }
                }

                LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    items(results) { game ->
                        Surface(color = Color(0xFF1B2330), shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth().clickable {
                                placeId = game.placeId
                                joinPlace(game.placeId)
                            }) {
                            Column(Modifier.padding(10.dp)) {
                                Text(game.name, color = Color.White, fontWeight = FontWeight.Medium)
                                Text("PlaceId: " + game.placeId + " · tap to join", color = Color(0xFF9AA9BD), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }

                if (activeRoom.isNotBlank()) {
                    Text("Chat · " + activeRoom, color = Color(0xFF83B7FF), fontWeight = FontWeight.SemiBold)
                    LazyColumn(Modifier.heightIn(max = 170.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        items(messages.takeLast(80)) { line ->
                            Text(line, color = Color(0xFFD7DEEA), style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                        OutlinedTextField(message, { message = it.take(200) }, label = { Text("Message") },
                            modifier = Modifier.weight(1f), singleLine = true)
                        Button(onClick = {
                            val text = message.trim()
                            if (text.isNotEmpty()) {
                                socket?.send(JSONObject().put("type", "message").put("text", text).toString())
                                message = ""
                            }
                        }, enabled = message.isNotBlank()) { Text("Send") }
                    }
                }
            }
        }
    }
}
