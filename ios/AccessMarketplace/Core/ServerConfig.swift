// ServerConfig.swift — backend address.
// setup.sh rewrites this file with the Mac's LAN IP so a real iPhone
// can reach the backend over Wi-Fi. Default works for the simulator.
enum ServerConfig {
    static let apiBaseURL = "http://localhost:8000/api"
}
