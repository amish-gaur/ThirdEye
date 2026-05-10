import SwiftUI

struct CameraNode: Identifiable, Hashable {
    let id: String
    let name: String
    let online: Bool
    let gradient: CameraTileGradient

    static let mockMesh: [CameraNode] = [
        CameraNode(id: "node_amish",   name: "Front porch", online: true,  gradient: .frontPorch),
        CameraNode(id: "node_aditya",  name: "Driveway",    online: true,  gradient: .driveway),
        CameraNode(id: "node_rishab",  name: "Backyard",    online: true,  gradient: .backyard),
        CameraNode(id: "node_garage",  name: "Garage",      online: false, gradient: .garage),
    ]
}
