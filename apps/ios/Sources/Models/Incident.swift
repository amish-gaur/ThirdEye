import SwiftUI

enum Tier: Int, Codable, CaseIterable, Identifiable {
    case ambient = 1, notice = 2, alert = 3, emergency = 4
    var id: Int { rawValue }

    var label: String {
        switch self {
        case .ambient:   return "AMBIENT"
        case .notice:    return "NOTICE"
        case .alert:     return "ALERT"
        case .emergency: return "EMERGENCY"
        }
    }

    /// Dot color — small severity indicator on light cards.
    var dot: Color {
        switch self {
        case .ambient:   return Color(hex: "#717182")           // muted gray
        case .notice:    return Color(hex: "#F1C8A5")           // warm sand
        case .alert:     return Color(hex: "#D4183D")           // destructive red
        case .emergency: return Color(hex: "#030213")           // near-black
        }
    }

    /// Background tone for severity badges on light cards.
    var bg: Color {
        switch self {
        case .ambient:   return Color(hex: "#717182").opacity(0.10)
        case .notice:    return Color(hex: "#F1C8A5").opacity(0.30)
        case .alert:     return Color(hex: "#D4183D").opacity(0.10)
        case .emergency: return Color(hex: "#030213").opacity(0.92)
        }
    }

    /// Text color on the severity bg.
    var fg: Color {
        switch self {
        case .ambient:   return Color(hex: "#717182")
        case .notice:    return Color(hex: "#7A1521")
        case .alert:     return Color(hex: "#D4183D")
        case .emergency: return .white
        }
    }
}

struct Incident: Identifiable, Hashable {
    let id: UUID
    let tier: Tier
    let scene: String           // e.g. "the front porch"
    let suspectDescription: String
    let summary: String
    let timeElapsed: String     // human-readable, e.g. "moments ago"
    let cameraNode: String      // e.g. "Front porch"

    static let mockActive = Incident(
        id: UUID(),
        tier: .alert,
        scene: "the front porch",
        suspectDescription: "Tall man in a black hoodie",
        summary: "Picked up a package from the porch and walked off",
        timeElapsed: "moments ago",
        cameraNode: "Front porch"
    )

    static let mockHistory: [Incident] = [
        Incident(id: UUID(), tier: .notice,  scene: "the driveway",   suspectDescription: "Delivery driver in uniform",     summary: "Dropped off a parcel",                       timeElapsed: "2h ago",  cameraNode: "Driveway"),
        Incident(id: UUID(), tier: .ambient, scene: "the front porch",suspectDescription: "Resident",                       summary: "Walked through",                              timeElapsed: "4h ago",  cameraNode: "Front porch"),
        Incident(id: UUID(), tier: .emergency,scene: "the backyard",  suspectDescription: "Person in dark jacket",          summary: "Ran across the yard with an item",            timeElapsed: "yesterday", cameraNode: "Backyard"),
        Incident(id: UUID(), tier: .ambient, scene: "the garage",     suspectDescription: "Resident",                       summary: "Entered through the side door",               timeElapsed: "yesterday", cameraNode: "Garage"),
    ]
}
