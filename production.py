import os
from async_server import app

# Production configurations
class ProductionConfig:
    # File upload limits
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', '/tmp/svg_uploads')
    JOBS_FOLDER = os.environ.get('JOBS_FOLDER', '/tmp/svg_jobs')
    
    # Processing limits
    MAX_WORKERS = int(os.environ.get('MAX_WORKERS', '4'))
    BATCH_SIZE = int(os.environ.get('BATCH_SIZE', '5'))  # Smaller batches for large datasets
    
    # Job management
    JOB_CLEANUP_HOURS = int(os.environ.get('JOB_CLEANUP_HOURS', '2'))
    MAX_CONCURRENT_JOBS = int(os.environ.get('MAX_CONCURRENT_JOBS', '10'))
    
    # Performance optimizations
    IMAGE_RESIZE_SIZE = (200, 200)  # Smaller size for faster processing
    SIMILARITY_THRESHOLD = 0.9  # Lower threshold for faster processing

# Apply production configurations
app.config['MAX_CONTENT_LENGTH'] = ProductionConfig.MAX_CONTENT_LENGTH

# Create necessary directories
os.makedirs(ProductionConfig.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ProductionConfig.JOBS_FOLDER, exist_ok=True)

if __name__ == "__main__":
    # Production server configuration
    import gunicorn.app.base
    
    class StandaloneApplication(gunicorn.app.base.BaseApplication):
        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()
        
        def load_config(self):
            config = {key: value for key, value in self.options.items()
                     if key in self.cfg.settings and value is not None}
            for key, value in config.items():
                self.cfg.set(key.lower(), value)
        
        def load(self):
            return self.application
    
    options = {
        'bind': '0.0.0.0:5000',
        'workers': 2,
        'worker_class': 'gthread',
        'threads': 4,
        'timeout': 300,
        'keepalive': 30,
        'max_requests': 1000,
        'max_requests_jitter': 100,
        'worker_connections': 1000,
        'preload_app': True
    }
    
    StandaloneApplication(app, options).run() 