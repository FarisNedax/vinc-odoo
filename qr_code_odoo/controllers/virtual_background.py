from odoo import http
from odoo.http import request
from odoo.tools.misc import file_path
import os
import logging

_logger = logging.getLogger(__name__)

class VirtualBackgroundController(http.Controller):
    
    @http.route('/qr_code_odoo/virtual_bg/list', type='jsonrpc', auth='public')
    def list_backgrounds(self):
        """List available virtual backgrounds dynamically from the filesystem."""
        try:
            # Resolve the virtual-background directory via file_path — the
            # Odoo 17+ replacement for get_module_resource (which is deprecated
            # and will be removed in a future major release).
            try:
                bg_path = file_path('qr_code_odoo/static/src/img/virtual_bg')
            except (FileNotFoundError, ValueError):
                bg_path = None

            if not bg_path or not os.path.exists(bg_path):
                _logger.warning("Virtual background directory not found.")
                return {'error': 'Background directory not found'}
                
            backgrounds = []
            valid_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
            
            # List all files
            files = os.listdir(bg_path)
            
            for filename in files:
                name, ext = os.path.splitext(filename)
                if ext.lower() in valid_extensions:
                    
                    key = name
                    
                    # Create a human-readable name
                    # Remove 'bg_' prefix for display if present
                    display_name = name
                    if display_name.startswith('bg_'):
                        display_name = display_name[3:]
                    
                    readable_name = display_name.replace('_', ' ').replace('-', ' ').title()
                    
                    # Construct the web-accessible URL
                    # NOTE: Updated path for qr_code_odoo
                    url = f'/qr_code_odoo/static/src/img/virtual_bg/{filename}'
                    
                    backgrounds.append({
                        'key': key,
                        'name': readable_name,
                        'src': url,
                        'filename': filename
                    })
            
            # Sort alphabetically
            backgrounds.sort(key=lambda x: x['name'])
            
            return {'backgrounds': backgrounds}
            
        except Exception as e:
            _logger.error(f"Error listing virtual backgrounds: {e}", exc_info=True)
            return {'error': str(e)}
