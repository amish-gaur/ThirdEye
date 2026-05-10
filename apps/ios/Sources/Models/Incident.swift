import SwiftUI

enum Tier: Int, Codable, CaseIterable, Identifiable, Hashable {
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

    // Incredibles palette — matches IncidentRow.tsx TIER table.
    var bg: Color {
        switch self {
        case .ambient:   return Color(hex: "#cfc4a6")
        case .notice:    return Hue.gold
        case .alert:     return Hue.orange
        case .emergency: return Hue.red
        }
    }

    var fg: Color {
        switch self {
        case .ambient, .notice: return Hue.ink
        case .alert, .emergency: return Color(hex: "#fff5e1")
        }
    }
}
