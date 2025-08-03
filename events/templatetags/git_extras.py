from django import template
from events.utils import get_git_version

register = template.Library()

@register.simple_tag
def get_git_version_info():
    """
    Template tag to get git version information.
    Returns a dictionary with git version details or None if not available.
    """
    return get_git_version()

@register.simple_tag
def get_git_version_display():
    """
    Template tag to get a formatted git version string for display.
    Returns a formatted string showing the git version information.
    """
    version_info = get_git_version()
    if not version_info:
        return "Unknown Version"
    
    parts = []
    
    # Add tag if available
    if version_info.get('latest_tag'):
        parts.append(f"v{version_info['latest_tag']}")
    
    # Add branch name (but not if it's main/master)
    branch = version_info.get('branch_name', '')
    if branch and branch not in ['main', 'master']:
        parts.append(f"({branch})")
    
    # Add commit hash
    if version_info.get('commit_hash'):
        parts.append(version_info['commit_hash'])
    
    # Add indicator for uncommitted changes
    if version_info.get('has_uncommitted'):
        parts.append("+")
    
    return " ".join(parts) if parts else "Unknown Version"

@register.simple_tag
def get_git_version_link():
    """
    Template tag to get git version information with a link to the commit.
    Returns a dictionary with version info and link data.
    """
    version_info = get_git_version()
    if not version_info:
        return None
    
    # Get the full commit hash for the link
    try:
        import subprocess
        import os
        git_root = subprocess.check_output(
            ['git', 'rev-parse', '--show-toplevel'],
            cwd=os.getcwd(),
            stderr=subprocess.PIPE,
            universal_newlines=True
        ).strip()
        
        full_commit_hash = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            cwd=git_root,
            stderr=subprocess.PIPE,
            universal_newlines=True
        ).strip()
        
        # Get commit date
        commit_date = subprocess.check_output(
            ['git', 'log', '-1', '--format=%cd', '--date=short'],
            cwd=git_root,
            stderr=subprocess.PIPE,
            universal_newlines=True
        ).strip()
        
        # Get remote URL for GitHub link
        try:
            remote_url = subprocess.check_output(
                ['git', 'config', '--get', 'remote.origin.url'],
                cwd=git_root,
                stderr=subprocess.PIPE,
                universal_newlines=True
            ).strip()
            
            # Convert SSH URL to HTTPS if needed
            if remote_url.startswith('git@'):
                remote_url = remote_url.replace('git@github.com:', 'https://github.com/').replace('.git', '')
            elif remote_url.startswith('https://'):
                remote_url = remote_url.replace('.git', '')
            
            commit_url = f"{remote_url}/commit/{full_commit_hash}"
        except subprocess.CalledProcessError:
            commit_url = None
            
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit_url = None
        commit_date = None
    
    return {
        'version_info': version_info,
        'commit_url': commit_url,
        'full_commit_hash': full_commit_hash if 'full_commit_hash' in locals() else None,
        'commit_date': commit_date
    }

@register.simple_tag
def get_git_commit_date():
    """
    Simple template tag to get just the commit date.
    Returns the commit date as a string or None if not available.
    """
    try:
        import subprocess
        import os
        git_root = subprocess.check_output(
            ['git', 'rev-parse', '--show-toplevel'],
            cwd=os.getcwd(),
            stderr=subprocess.PIPE,
            universal_newlines=True
        ).strip()
        
        commit_date = subprocess.check_output(
            ['git', 'log', '-1', '--format=%cd', '--date=short'],
            cwd=git_root,
            stderr=subprocess.PIPE,
            universal_newlines=True
        ).strip()
        
        return commit_date
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None 