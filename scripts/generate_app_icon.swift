#!/usr/bin/env swift

import AppKit
import Foundation

let outputPath = CommandLine.arguments.dropFirst().first

guard let outputPath else {
    fputs("Usage: swift generate_app_icon.swift <iconset-dir>\n", stderr)
    exit(1)
}

let iconsetURL = URL(fileURLWithPath: outputPath, isDirectory: true)
let fileManager = FileManager.default

if fileManager.fileExists(atPath: iconsetURL.path) {
    try? fileManager.removeItem(at: iconsetURL)
}
try fileManager.createDirectory(at: iconsetURL, withIntermediateDirectories: true)

let iconSpecs: [(Int, String)] = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]

let backgroundColors = [
    NSColor(calibratedRed: 0.09, green: 0.19, blue: 0.37, alpha: 1.0),
    NSColor(calibratedRed: 0.15, green: 0.29, blue: 0.52, alpha: 1.0),
    NSColor(calibratedRed: 0.78, green: 0.39, blue: 0.27, alpha: 1.0),
]

func drawIcon(in rect: CGRect) {
    let inset = rect.width * 0.05
    let canvas = rect.insetBy(dx: inset, dy: inset)
    let radius = rect.width * 0.215
    let backgroundPath = NSBezierPath(roundedRect: canvas, xRadius: radius, yRadius: radius)

    let gradient = NSGradient(colors: backgroundColors) ?? NSGradient(starting: .black, ending: .darkGray)!
    gradient.draw(in: backgroundPath, angle: -38)

    NSGraphicsContext.current?.cgContext.saveGState()
    backgroundPath.addClip()

    let glowRect = CGRect(
        x: canvas.maxX - canvas.width * 0.56,
        y: canvas.maxY - canvas.height * 0.52,
        width: canvas.width * 0.76,
        height: canvas.height * 0.76
    )
    NSColor.white.withAlphaComponent(0.18).setFill()
    NSBezierPath(ovalIn: glowRect).fill()

    let bottomGlowRect = CGRect(
        x: canvas.minX + canvas.width * 0.22,
        y: canvas.minY + canvas.height * 0.16,
        width: canvas.width * 0.56,
        height: canvas.height * 0.14
    )
    NSColor.white.withAlphaComponent(0.08).setFill()
    NSBezierPath(ovalIn: bottomGlowRect).fill()

    NSGraphicsContext.current?.cgContext.restoreGState()

    NSColor.white.withAlphaComponent(0.12).setStroke()
    backgroundPath.lineWidth = max(2, rect.width * 0.008)
    backgroundPath.stroke()

    let contentRect = canvas.insetBy(dx: canvas.width * 0.22, dy: canvas.height * 0.18)
    let maxBarHeight = contentRect.height * 0.82
    let heights: [CGFloat] = [0.34, 0.58, 0.82, 0.58, 0.34]
    let barWidth = contentRect.width * 0.102
    let gap = contentRect.width * 0.072
    let totalWidth = barWidth * CGFloat(heights.count) + gap * CGFloat(heights.count - 1)
    let startX = contentRect.midX - totalWidth / 2

    let barShadow = NSShadow()
    barShadow.shadowBlurRadius = rect.width * 0.03
    barShadow.shadowOffset = NSSize(width: 0, height: -rect.width * 0.012)
    barShadow.shadowColor = NSColor.black.withAlphaComponent(0.18)
    barShadow.set()

    for (index, factor) in heights.enumerated() {
        let barHeight = maxBarHeight * factor
        let x = startX + CGFloat(index) * (barWidth + gap)
        let y = canvas.midY - barHeight / 2
        let barRect = CGRect(x: x, y: y, width: barWidth, height: barHeight)
        let barPath = NSBezierPath(roundedRect: barRect, xRadius: barWidth / 2, yRadius: barWidth / 2)
        let alpha = index == 2 ? 0.98 : 0.93
        NSColor(calibratedRed: 1.0, green: 0.965, blue: 0.94, alpha: alpha).setFill()
        barPath.fill()
    }
}

func pngData(size: Int) -> Data? {
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: size,
        pixelsHigh: size,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else {
        return nil
    }

    rep.size = NSSize(width: size, height: size)

    NSGraphicsContext.saveGraphicsState()
    guard let context = NSGraphicsContext(bitmapImageRep: rep) else {
        NSGraphicsContext.restoreGraphicsState()
        return nil
    }

    NSGraphicsContext.current = context
    context.cgContext.setShouldAntialias(true)
    context.cgContext.clear(CGRect(x: 0, y: 0, width: size, height: size))
    drawIcon(in: CGRect(x: 0, y: 0, width: size, height: size))
    context.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()

    return rep.representation(using: .png, properties: [:])
}

for (size, filename) in iconSpecs {
    guard let data = pngData(size: size) else {
        fputs("Failed to render \(filename)\n", stderr)
        exit(1)
    }

    try data.write(to: iconsetURL.appendingPathComponent(filename))
}
