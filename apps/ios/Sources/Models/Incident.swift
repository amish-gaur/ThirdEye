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

    /// Dot color — used as the small severity indicator on tiles, badges.
    var dot: Color {
        switch self {
        case .ambient:   return Color(hex: "#C98A93")
        case .notice:    return Color(hex: "#9A3142")
        case .alert:     return Color(hex: "#B85968")
        case .emergency: return Color(hex: "#E5B4BB")
        }
    }

    /// Background tone for severity badges / hero.
    var bg: Color {
        switch self {
        case .ambient:   return Color(red: 201/255, green: 138/255, blue: 147/255).opacity(0.14)
        case .notice:    return Color(red: 154/255, green: 49/255,  blue: 66/255).opacity(0.18)
        case .alert:     return Color(red: 94/255,  green: 21/255,  blue: 33/255).opacity(0.45)
        case .emergency: return Color(red: 31/255,  green: 5/255,   blue: 10/255).opacity(0.85)
        }
    }

    /// Text color on the severity bg.
    var fg: Color {
        switch self {
        case .ambient, .notice: return Color(hex: "#E5B4BB")
        case .alert:            return Color(hex: "#F2D9DC")
        case .emergency:        return Color(hex: "#FBF1E7")
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
