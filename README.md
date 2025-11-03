# Local Photo Analyzer

A local deployment of the Photo Analyzer application that connects to a local Postgres database (defaults to localhost).

## Features

- 🏠 **Local Development**: Run the application locally on your machine
- 🗄️ **Postgres Connection**: Connects to your local Postgres database
- 📸 **Photo Gallery**: Browse all photos from your database
- 👥 **Face Analysis**: View facial recognition statistics and insights
- 🔍 **Duplicate Detection**: See detected duplicate photos
- 🔧 **Admin Dashboard**: System statistics and database management

## Quick Start

### 1. Prerequisites

- Python 3.8 or higher
- Local Postgres instance (defaults to localhost:5432) or valid DB_HOST/DB_* environment variables
- PostgreSQL installed locally for database storage

### 2. Setup

```bash
# Clone or navigate to the local-photo-analyzer directory
cd local-photo-analyzer

# Run the setup script
python3 setup_local.py
```

The setup script will:
- Install required dependencies
- Verify a local Postgres connection (or validate DB_* env vars)
- Test the database connection
- Create necessary directories

# Run the Application

```bash
python3 simple_app.py
```

The application will start on `http://localhost:5001`

## Manual Configuration

If auto-configuration fails, you can manually set environment variables:

### Option 1: Environment Variables

```bash
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=photo_analyzer
export DB_USER=postgres
export DB_PASSWORD=your-password
```

### Option 2: .env File

Create a `.env` file in the project directory:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=photo_analyzer
DB_USER=postgres
DB_PASSWORD=your-password
```

## Application Structure

```
local-photo-analyzer/
├── simple_app.py          # Main Flask application
├── configure_rds.py       # RDS auto-configuration script
├── setup_local.py        # Setup and installation script
├── requirements.txt       # Python dependencies
├── README.md             # This file
├── templates/            # HTML templates
│   ├── index.html        # Home page with photo grid
│   ├── gallery.html      # Gallery view
│   ├── faces.html        # Face analysis page
│   ├── duplicates.html   # Duplicate photos page
│   ├── admin.html        # Admin dashboard
│   └── photo_details.html # Individual photo details
└── static/
    └── uploads/          # Local upload directory (created automatically)
```

## Available Pages

- **Home** (`/`): Photo grid with thumbnails and basic info
- **Gallery** (`/gallery`): Enhanced gallery view with statistics
- **Face Analysis** (`/faces`): Facial recognition insights and top photos
- **Duplicates** (`/duplicates`): Detected duplicate photos
- **Admin** (`/admin`): System statistics and database information
- **Photo Details** (`/photo/<id>`): Detailed view of individual photos

## API Endpoints

- `GET /api/photos` - List all photos (JSON)
- `GET /api/photo/<id>` - Get photo details (JSON)
- `GET /health` - Health check and database status

## Features

### Read-Only Access
This local deployment is designed for **read-only** access to your production data. It does not include upload functionality to prevent accidental modifications to your production database.

### Real-Time Data
All data displayed is live from your Postgres database, so you'll see the most current state of your photo collection.

### Face Recognition
View comprehensive facial recognition statistics including:
- Total faces detected
- Photos with faces
- Average confidence scores
- Photos with the most faces

### Duplicate Detection
Browse detected duplicate photos with:
- Similarity scores
- Detection methods used
- Visual comparison tools

## Troubleshooting

### Database Connection Issues

1. **Check Database Configuration**:
   ```bash
   python -c "from database_config import get_database_info; print(get_database_info())"
   ```

2. **Verify PostgreSQL Installation**:
   ```bash
   psql --version
   ```

3. **Test Manual Connection**:
   ```bash
   python3 -c "import psycopg2; conn = psycopg2.connect(host='YOUR_HOST', database='photo_analyzer', user='postgres', password='YOUR_PASSWORD'); print('Connected!')"
   ```

### Common Issues

- **Port 5001 in use**: Change the port in `simple_app.py` or kill the process using port 5001
- **Missing dependencies**: Run `pip install -r requirements.txt`
- **Database credentials**: Set up credentials in `.env` file
- **Database timeout**: Check security groups and network connectivity

### Environment Variables

The application uses these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_HOST` | PostgreSQL host | localhost |
| `DB_PORT` | Database port | 5432 |
| `DB_NAME` | Database name | photo_analyzer |
| `DB_USER` | Database user | postgres |
| `DB_PASSWORD` | Database password | From Parameter Store |
| `DB_TYPE` | Database type (postgres/sqlite) | sqlite |

## Security Notes

- This application connects to your production database
- Database credentials are configured in the `.env` file
- No upload functionality to prevent accidental data modification
- Local access only (binds to localhost by default)

## Development

To modify the application:

1. Edit `simple_app.py` for backend changes
2. Modify templates in `templates/` for frontend changes
3. Update `requirements.txt` for new dependencies
4. Test changes locally before deploying

## Support

If you encounter issues:

1. Check the console output for error messages
2. Verify your PostgreSQL installation and credentials
3. Ensure PostgreSQL is running and accepting connections
4. Check the `/health` endpoint for system status

---

**Note**: This is a local interface to your Postgres database. All data shown is live data from your local database.