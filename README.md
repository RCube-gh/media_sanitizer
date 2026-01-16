# 🛡️ Media Sanitizer

> **"Sanitize your media, Protect your fortress."**

## 📖 Overview
**Media Sanitizer** is a security-focused tool designed to perform **Content Disarm and Reconstruction (CDR)** on suspicious media files (videos, images, audio).
Instead of detecting malware, it assumes *all* input is malicious and reconstructs the file from scratch using safe codecs and containers. This process eliminates steganography, polyglot payloads, malicious metadata, and exploited codec vulnerabilities.

怪しいサイトから収集したメディアファイルを「検知」するのではなく、サンドボックス内で一度分解し、**「完全に新しいファイルとして再構築（サニタイズ）」**することで無害化します。

## ✨ Core Features
*   **Zero-Trust Architecture**: Treats every file as a potential threat.
*   **CDR Levels**:
    *   **Level 1 (Remux)**: Safe container swapping.
    *   **Level 2 (Transcode)**: Full re-encoding to eliminate deep-seated threats (Default).
    *   **Level 3 (Hardcore)**: Subtitle burn-in to neutralize script-based attacks.
*   **Isolation**: Runs all processing within a network-isolated Docker container (`network: none`).
*   **Privacy First**: Strips all metadata (EXIF, GPS, device info).

## 🚀 Getting Started

### Prerequisites
*   Docker Desktop
*   Python 3.11+

### Installation
(Coming Soon)

## ⚠️ Disclaimer
This tool is intended for personal security and educational purposes. While it significantly reduces risk, no security solution is 100% foolproof. Always practice safe browsing habits.

---
**Author**: 俺
