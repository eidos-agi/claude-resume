# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.9] - 2026-03-22

### Fixed
- Replaced `claude -p` window summaries with no-LLM adapter (faster, no API dependency)

## [0.1.8] - 2026-03-22

### Fixed
- Fixed image URLs to absolute raw GitHub paths for PyPI rendering
- Re-processed screenshots without quantize (was destroying text quality)

### Changed
- Renamed 'Claude Resume' to 'resume-resume' across all references
- Replaced example screenshots with new Gemini images (watermark-free)
- Compressed logo: 7MB PNG to 333KB
- Removed mcp-self-report dependency, switched to PyPI-ready deps
- Added LICENSE file

## [0.1.0] - 2026-03-20

### Added
- Initial release
- Post-crash Claude Code session recovery TUI
- Session discovery, caching, and classification
- MCP server for agent-driven session recovery
