import os
import sys
from django.core.wsgi import get_wsgi_application

# 1. Get the absolute path to the directory containing wsgi.py
# (This is NumberScanner/numbersys/numbersys/)
current_dir = os.path.dirname(__file__)

# 2. Add the folder containing 'manage.py' to the Python path
# (This moves up one level to NumberScanner/numbersys/)
project_root = os.path.abspath(os.path.join(current_dir, '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

# 3. Add the GitHub Root to the Python path 
# (This moves up two levels to NumberScanner/)
repo_root = os.path.abspath(os.path.join(project_root, '..'))
if repo_root not in sys.path:
    sys.path.append(repo_root)

# 4. Set the settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'numbersys.settings')

application = get_wsgi_application()

# This is a common requirement for Vercel to find the 'app'
app = application