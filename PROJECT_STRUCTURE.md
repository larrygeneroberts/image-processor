```markdown
# Photo Management System - Project Structure

## 🎯 Core Application
- `simple_app.py` - Main Flask web application
- `database_config.py` - Database configuration and connection management
- `requirements.txt` - Python dependencies
- `.env` - Environment variables (not in git)

## 🔧 Utilities
- `utils/cleanup_disk_space.py` - Disk space management utility

## 🎨 Web Interface
- `templates/` - HTML templates for web interface
  - `index.html` - Main upload and processing interface
  - `deduplication.html` - Deduplication management interface
- `static/` - Static web assets (CSS, JS, images)

## 📁 Data Directories
- `processed_photos/` - Local processed photo storage
- `duplicates/` - Local duplicate file storage

## 🔧 Configuration
- `.gitignore` - Git ignore rules
- `LICENSE` - Project license
- `README.md` - Project documentation

## 🚀 Quick Start
1. Install dependencies: `pip install -r requirements.txt`
2. Configure environment: Copy `.env.example` to `.env` and configure
3. Run application: `python simple_app.py`
4. Access web interface: http://localhost:5001

## 🛠️ Utilities Usage
- Disk cleanup: `python utils/cleanup_disk_space.py`
- Data exploration utilities: see scripts in `utils/` (check file headers for usage notes)

```
