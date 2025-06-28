"""
Custom middleware for serving static files in production
"""
import os
from django.conf import settings
from django.http import Http404, HttpResponse
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.contrib.staticfiles.finders import find


class StaticFilesMiddleware:
    """
    Middleware to serve static files in production when DEBUG=False
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if this is a static file request
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return self.serve_static_file(request)
        
        return self.get_response(request)

    def serve_static_file(self, request):
        """Serve static files"""
        path = request.path
        
        # Remove the /static/ or /media/ prefix
        if path.startswith('/static/'):
            file_path = path[8:]  # Remove '/static/'
            root_dir = settings.STATIC_ROOT
        elif path.startswith('/media/'):
            file_path = path[7:]  # Remove '/media/'
            root_dir = settings.MEDIA_ROOT
        else:
            raise Http404("Not found")

        # Construct the full file path
        full_path = os.path.join(root_dir, file_path)
        
        # Check if file exists
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            raise Http404("File not found")

        # Get file extension for content type
        _, ext = os.path.splitext(full_path)
        content_type = self.get_content_type(ext)
        
        # Read and serve the file
        try:
            with open(full_path, 'rb') as f:
                content = f.read()
            
            response = HttpResponse(content, content_type=content_type)
            
            # Add cache headers for static files
            if path.startswith('/static/'):
                response['Cache-Control'] = 'public, max-age=31536000'  # 1 year
            
            return response
        except Exception:
            raise Http404("Error reading file")

    def get_content_type(self, ext):
        """Get content type based on file extension"""
        content_types = {
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.svg': 'image/svg+xml',
            '.ico': 'image/x-icon',
            '.woff': 'font/woff',
            '.woff2': 'font/woff2',
            '.ttf': 'font/ttf',
            '.eot': 'application/vnd.ms-fontobject',
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.html': 'text/html',
            '.xml': 'application/xml',
        }
        return content_types.get(ext.lower(), 'application/octet-stream') 