#!/usr/bin/env python3
import requests
import yaml

def check_branch_exists(repo, branch):
    """Check if a branch exists in a GitHub repository"""
    url = f"https://api.github.com/repos/{repo}/branches/{branch}"
    response = requests.get(url)
    return response.status_code == 200

def main():
    with open("projects.yaml", 'r') as f:
        config = yaml.safe_load(f)
    
    print("Checking branches for custom packages...")
    
    for project in config['custom_packages']:
        repo = project['repo']
        branch = project.get('branch', 'main')
        
        if check_branch_exists(repo, branch):
            print(f"✓ {repo} - branch '{branch}' exists")
        else:
            print(f"✗ {repo} - branch '{branch}' NOT FOUND!")

if __name__ == "__main__":
    main()