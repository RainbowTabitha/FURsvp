from django.core.management.base import BaseCommand
import subprocess
import os

class Command(BaseCommand):
    help = 'Gets the current git version information'

    def handle(self, *args, **options):
        try:
            # Get the git repository root directory
            git_root = subprocess.check_output(
                ['git', 'rev-parse', '--show-toplevel'],
                cwd=os.getcwd(),
                stderr=subprocess.PIPE,
                universal_newlines=True
            ).strip()
            
            # Get the current commit hash
            commit_hash = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                cwd=git_root,
                stderr=subprocess.PIPE,
                universal_newlines=True
            ).strip()
            
            # Get the current branch name
            branch_name = subprocess.check_output(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=git_root,
                stderr=subprocess.PIPE,
                universal_newlines=True
            ).strip()
            
            # Get the latest tag if available
            try:
                latest_tag = subprocess.check_output(
                    ['git', 'describe', '--tags', '--abbrev=0'],
                    cwd=git_root,
                    stderr=subprocess.PIPE,
                    universal_newlines=True
                ).strip()
            except subprocess.CalledProcessError:
                latest_tag = None
            
            # Check if there are uncommitted changes
            try:
                subprocess.check_output(
                    ['git', 'diff-index', '--quiet', 'HEAD', '--'],
                    cwd=git_root,
                    stderr=subprocess.PIPE
                )
                has_uncommitted = False
            except subprocess.CalledProcessError:
                has_uncommitted = True
            
            version_info = {
                'commit_hash': commit_hash,
                'branch_name': branch_name,
                'latest_tag': latest_tag,
                'has_uncommitted': has_uncommitted
            }
            
            self.stdout.write(self.style.SUCCESS(f'Git version info: {version_info}'))
            return version_info
            
        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f'Error getting git version: {e}'))
            return None
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Unexpected error: {e}'))
            return None 