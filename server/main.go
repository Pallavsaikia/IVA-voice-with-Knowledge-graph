package main

import (
    "encoding/json"
    "log"
    "math/rand"
    "net/http"
    "strings"
    "sync"
    "time"
    "github.com/gorilla/websocket"
)

type ClientType string

const (
    ClientTypeUser  ClientType = "user"
    ClientTypeAgent ClientType = "agent"
)

type Client struct {
    conn     *websocket.Conn
    room     string
    clientId string
    clientType ClientType
    metadata map[string]interface{}
}

type Message struct {
    Type      string                 `json:"type"`
    From      string                 `json:"from"`
    To        []string               `json:"to,omitempty"` // Empty means broadcast to all
    Data      interface{}            `json:"data"`
    Metadata  map[string]interface{} `json:"metadata,omitempty"`
    Timestamp int64                  `json:"timestamp"`
}

type ServerInfo struct {
    Address string `json:"address"`
    Port    int    `json:"port"`
}

type RoomInfo struct {
    RoomId    string            `json:"roomId"`
    Users     map[string]*Client `json:"users"`
    Agents    map[string]*Client `json:"agents"`
    CreatedAt int64             `json:"createdAt"`
}

var (
    rooms     = make(map[string]*RoomInfo)
    roomsMu   sync.RWMutex
    servers   []ServerInfo
    serversMu sync.Mutex
    rnd       = rand.New(rand.NewSource(time.Now().UnixNano()))
)

var upgrader = websocket.Upgrader{
    CheckOrigin: func(r *http.Request) bool {
        return true
    },
}

func handleWebSocket(w http.ResponseWriter, r *http.Request) {
    roomId := r.URL.Query().Get("room")
    clientId := r.URL.Query().Get("clientId")
    clientType := ClientType(r.URL.Query().Get("type"))
    
    if roomId == "" {
        http.Error(w, "room query param required", http.StatusBadRequest)
        return
    }
    
    if clientId == "" {
        http.Error(w, "clientId query param required", http.StatusBadRequest)
        return
    }
    
    if clientType != ClientTypeUser && clientType != ClientTypeAgent {
        clientType = ClientTypeUser // default to user
    }
    
    conn, err := upgrader.Upgrade(w, r, nil)
    if err != nil {
        log.Println("Upgrade error:", err)
        return
    }
    
    client := &Client{
        conn:       conn,
        room:       roomId,
        clientId:   clientId,
        clientType: clientType,
        metadata:   make(map[string]interface{}),
    }
    
    // Add client to room
    addClientToRoom(roomId, client)
    
    log.Printf("Client %s (%s) joined room: %s", clientId, clientType, roomId)
    
    // Send welcome message with room info
    sendWelcomeMessage(client)
    
    // Notify others about new client
    notifyClientJoined(roomId, client)
    
    // Handle messages - FIXED VERSION
    for {
        messageType, data, err := conn.ReadMessage()
        if err != nil {
            log.Printf("Read error (room %s, client %s): %v", roomId, clientId, err)
            break
        }
        
        switch messageType {
        case websocket.TextMessage:
            // Handle JSON messages
            var msg Message
            err := json.Unmarshal(data, &msg)
            if err != nil {
                log.Printf("JSON unmarshal error (room %s, client %s): %v", roomId, clientId, err)
                continue
            }
            
            msg.From = clientId
            msg.Timestamp = time.Now().UnixNano() / int64(time.Millisecond)
            
            handleMessage(roomId, client, &msg)
            
        case websocket.BinaryMessage:
            // Handle binary audio data - forward to appropriate clients
            if client.clientType == ClientTypeUser {
                forwardAudioToAgents(roomId, clientId, data)
            }
            // If it's from an agent, forward to users
            if client.clientType == ClientTypeAgent {
                forwardAudioToUsers(roomId, clientId, data)
            }
            
        default:
            log.Printf("Unknown message type: %d", messageType)
        }
    }
    
    // Remove client on disconnect
    removeClientFromRoom(roomId, client)
    notifyClientLeft(roomId, client)
    
    log.Printf("Client %s left room: %s", clientId, roomId)
    conn.Close()
}

func forwardAudioToAgents(roomId string, fromClientId string, audioData []byte) {
    roomsMu.RLock()
    room := rooms[roomId]
    roomsMu.RUnlock()
    
    if room == nil {
        return
    }
    
    // Forward audio to all agents in the room
    for _, client := range room.Agents {
        if client.clientId != fromClientId {
            err := client.conn.WriteMessage(websocket.BinaryMessage, audioData)
            if err != nil {
                log.Printf("Audio forward error to agent %s: %v", client.clientId, err)
            }
        }
    }
}

func forwardAudioToUsers(roomId string, fromClientId string, audioData []byte) {
    roomsMu.RLock()
    room := rooms[roomId]
    roomsMu.RUnlock()
    
    if room == nil {
        return
    }
    
    // Forward audio to all users in the room
    for _, client := range room.Users {
        if client.clientId != fromClientId {
            err := client.conn.WriteMessage(websocket.BinaryMessage, audioData)
            if err != nil {
                log.Printf("Audio forward error to user %s: %v", client.clientId, err)
            }
        }
    }
}

func addClientToRoom(roomId string, client *Client) {
    roomsMu.Lock()
    defer roomsMu.Unlock()
    
    if rooms[roomId] == nil {
        rooms[roomId] = &RoomInfo{
            RoomId:    roomId,
            Users:     make(map[string]*Client),
            Agents:    make(map[string]*Client),
            CreatedAt: time.Now().UnixNano() / int64(time.Millisecond),
        }
    }
    
    if client.clientType == ClientTypeAgent {
        rooms[roomId].Agents[client.clientId] = client
    } else {
        rooms[roomId].Users[client.clientId] = client
    }
}

func removeClientFromRoom(roomId string, client *Client) {
    roomsMu.Lock()
    defer roomsMu.Unlock()
    
    room := rooms[roomId]
    if room == nil {
        return
    }
    
    if client.clientType == ClientTypeAgent {
        delete(room.Agents, client.clientId)
    } else {
        delete(room.Users, client.clientId)
    }
    
    // Clean up empty rooms
    if len(room.Users) == 0 && len(room.Agents) == 0 {
        delete(rooms, roomId)
    }
}

func handleMessage(roomId string, sender *Client, msg *Message) {
    switch msg.Type {
    case "broadcast":
        broadcastToRoom(roomId, sender, msg)
    case "selective":
        selectiveSend(roomId, sender, msg)
    case "agent_only":
        sendToAgents(roomId, sender, msg)
    case "user_only":
        sendToUsers(roomId, sender, msg)
    case "metadata":
        updateClientMetadata(sender, msg)
    default:
        // Default behavior is broadcast
        broadcastToRoom(roomId, sender, msg)
    }
}

func broadcastToRoom(roomId string, sender *Client, msg *Message) {
    roomsMu.RLock()
    room := rooms[roomId]
    roomsMu.RUnlock()
    
    if room == nil {
        return
    }
    
    // Send to all users except sender
    for _, client := range room.Users {
        if client != sender {
            sendMessageToClient(client, msg)
        }
    }
    
    // Send to all agents except sender
    for _, client := range room.Agents {
        if client != sender {
            sendMessageToClient(client, msg)
        }
    }
}

func selectiveSend(roomId string, sender *Client, msg *Message) {
    if len(msg.To) == 0 {
        broadcastToRoom(roomId, sender, msg)
        return
    }
    
    roomsMu.RLock()
    room := rooms[roomId]
    roomsMu.RUnlock()
    
    if room == nil {
        return
    }
    
    // Send to specific clients
    for _, targetId := range msg.To {
        // Check users first
        if client, exists := room.Users[targetId]; exists {
            sendMessageToClient(client, msg)
        }
        // Check agents
        if client, exists := room.Agents[targetId]; exists {
            sendMessageToClient(client, msg)
        }
    }
}

func sendToAgents(roomId string, sender *Client, msg *Message) {
    roomsMu.RLock()
    room := rooms[roomId]
    roomsMu.RUnlock()
    
    if room == nil {
        return
    }
    
    for _, client := range room.Agents {
        if client != sender {
            sendMessageToClient(client, msg)
        }
    }
}

func sendToUsers(roomId string, sender *Client, msg *Message) {
    roomsMu.RLock()
    room := rooms[roomId]
    roomsMu.RUnlock()
    
    if room == nil {
        return
    }
    
    for _, client := range room.Users {
        if client != sender {
            sendMessageToClient(client, msg)
        }
    }
}

func sendMessageToClient(client *Client, msg *Message) {
    err := client.conn.WriteJSON(msg)
    if err != nil {
        log.Printf("Write error to client %s: %v", client.clientId, err)
    }
}

func sendWelcomeMessage(client *Client) {
    roomsMu.RLock()
    room := rooms[client.room]
    roomsMu.RUnlock()
    
    if room == nil {
        return
    }
    
    // Prepare room participants info
    users := make([]string, 0, len(room.Users))
    agents := make([]string, 0, len(room.Agents))
    
    for id := range room.Users {
        users = append(users, id)
    }
    for id := range room.Agents {
        agents = append(agents, id)
    }
    
    welcomeMsg := &Message{
        Type: "welcome",
        From: "system",
        Data: map[string]interface{}{
            "roomId": client.room,
            "clientId": client.clientId,
            "clientType": client.clientType,
            "users": users,
            "agents": agents,
        },
        Timestamp: time.Now().UnixNano() / int64(time.Millisecond),
    }
    
    sendMessageToClient(client, welcomeMsg)
}

func notifyClientJoined(roomId string, newClient *Client) {
    msg := &Message{
        Type: "client_joined",
        From: "system",
        Data: map[string]interface{}{
            "clientId": newClient.clientId,
            "clientType": newClient.clientType,
        },
        Timestamp: time.Now().UnixNano() / int64(time.Millisecond),
    }
    
    broadcastToRoom(roomId, newClient, msg)
}

func notifyClientLeft(roomId string, leftClient *Client) {
    msg := &Message{
        Type: "client_left",
        From: "system",
        Data: map[string]interface{}{
            "clientId": leftClient.clientId,
            "clientType": leftClient.clientType,
        },
        Timestamp: time.Now().UnixNano() / int64(time.Millisecond),
    }
    
    broadcastToRoom(roomId, leftClient, msg)
}

func updateClientMetadata(client *Client, msg *Message) {
    if metadata, ok := msg.Data.(map[string]interface{}); ok {
        for key, value := range metadata {
            client.metadata[key] = value
        }
    }
}

// REST API Handlers

func handleRegister(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodPost {
        http.Error(w, "Only POST allowed", http.StatusMethodNotAllowed)
        return
    }
    
    var newServer ServerInfo
    if err := json.NewDecoder(r.Body).Decode(&newServer); err != nil {
        http.Error(w, "Invalid JSON", http.StatusBadRequest)
        return
    }
    
    serversMu.Lock()
    defer serversMu.Unlock()
    
    for _, s := range servers {
        if s.Address == newServer.Address && s.Port == newServer.Port {
            http.Error(w, "Already registered", http.StatusConflict)
            return
        }
    }
    
    servers = append(servers, newServer)
    w.WriteHeader(http.StatusCreated)
    json.NewEncoder(w).Encode(newServer)
}

func handleAllocate(w http.ResponseWriter, r *http.Request) {
    serversMu.Lock()
    defer serversMu.Unlock()
    
    if len(servers) == 0 {
        http.Error(w, "No servers available", http.StatusServiceUnavailable)
        return
    }
    
    selected := servers[rnd.Intn(len(servers))]
    json.NewEncoder(w).Encode(selected)
}

func handleList(w http.ResponseWriter, r *http.Request) {
    serversMu.Lock()
    defer serversMu.Unlock()
    
    json.NewEncoder(w).Encode(servers)
}

func handleRoomInfo(w http.ResponseWriter, r *http.Request) {
    roomId := strings.TrimPrefix(r.URL.Path, "/room/")
    if roomId == "" {
        http.Error(w, "Room ID required", http.StatusBadRequest)
        return
    }
    
    roomsMu.RLock()
    room := rooms[roomId]
    roomsMu.RUnlock()
    
    if room == nil {
        http.Error(w, "Room not found", http.StatusNotFound)
        return
    }
    
    users := make([]map[string]interface{}, 0, len(room.Users))
    agents := make([]map[string]interface{}, 0, len(room.Agents))
    
    for id, client := range room.Users {
        users = append(users, map[string]interface{}{
            "clientId": id,
            "metadata": client.metadata,
        })
    }
    
    for id, client := range room.Agents {
        agents = append(agents, map[string]interface{}{
            "clientId": id,
            "metadata": client.metadata,
        })
    }
    
    response := map[string]interface{}{
        "roomId":    roomId,
        "users":     users,
        "agents":    agents,
        "createdAt": room.CreatedAt,
    }
    
    json.NewEncoder(w).Encode(response)
}

func handleRoomList(w http.ResponseWriter, r *http.Request) {
    roomsMu.RLock()
    defer roomsMu.RUnlock()
    
    roomList := make([]map[string]interface{}, 0, len(rooms))
    
    for roomId, room := range rooms {
        roomList = append(roomList, map[string]interface{}{
            "roomId":     roomId,
            "userCount":  len(room.Users),
            "agentCount": len(room.Agents),
            "createdAt":  room.CreatedAt,
        })
    }
    
    json.NewEncoder(w).Encode(roomList)
}

func main() {
    http.HandleFunc("/ws", handleWebSocket)
    http.HandleFunc("/register", handleRegister)
    http.HandleFunc("/allocate", handleAllocate)
    http.HandleFunc("/list", handleList)
    http.HandleFunc("/room/", handleRoomInfo)
    http.HandleFunc("/rooms", handleRoomList)
    
    log.Println("Enhanced Server + Registry running on :8080")
    log.Println("WebSocket endpoints:")
    log.Println("  /ws?room=ROOM_ID&clientId=CLIENT_ID&type=user|agent")
    log.Println("REST API endpoints:")
    log.Println("  GET  /rooms - List all active rooms")
    log.Println("  GET  /room/ROOM_ID - Get room information")
    log.Println("  POST /register - Register a server")
    log.Println("  GET  /allocate - Get a random server")
    log.Println("  GET  /list - List all servers")
    
    log.Fatal(http.ListenAndServe(":8080", nil))
}