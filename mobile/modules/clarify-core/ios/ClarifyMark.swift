import SwiftUI

// Vector geometry of assets/icon.png, rendered at the activity's actual size.
struct ClarifyMark: Shape {
  func path(in rect: CGRect) -> Path {
    let bars: [CGRect] = [
      CGRect(x: 0.071, y: 0.403, width: 0.094, height: 0.186),
      CGRect(x: 0.255, y: 0.132, width: 0.093, height: 0.455),
      CGRect(x: 0.255, y: 0.681, width: 0.093, height: 0.188),
      CGRect(x: 0.438, y: 0.041, width: 0.093, height: 0.185),
      CGRect(x: 0.438, y: 0.270, width: 0.093, height: 0.458),
      CGRect(x: 0.438, y: 0.766, width: 0.093, height: 0.193),
      CGRect(x: 0.622, y: 0.132, width: 0.093, height: 0.189),
      CGRect(x: 0.622, y: 0.403, width: 0.093, height: 0.466),
      CGRect(x: 0.806, y: 0.404, width: 0.094, height: 0.186)
    ]
    var path = Path()
    for bar in bars {
      let frame = CGRect(x: rect.minX + bar.minX * rect.width, y: rect.minY + bar.minY * rect.height,
        width: bar.width * rect.width, height: bar.height * rect.height)
      path.addRoundedRect(in: frame, cornerSize: CGSize(width: frame.width / 2, height: frame.width / 2))
    }
    return path
  }
}
