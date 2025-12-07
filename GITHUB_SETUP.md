# GitHub Setup Instructions

Follow these steps to publish your project to GitHub.

## Step 1: Create GitHub Repository

1. Go to [https://github.com/new](https://github.com/new)
2. Fill in the repository details:
   - **Repository name**: `index-life-local`
   - **Description**: `Private local mood diary application - Track your daily mood offline`
   - **Visibility**: Choose `Public` or `Private`
   - **DO NOT** initialize with README, .gitignore, or license (we already have these)
3. Click **Create repository**

## Step 2: Push to GitHub

After creating the repository, GitHub will show you commands. Use these:

```bash
cd f:\index-life-local

# Add remote repository
git remote add origin https://github.com/YOUR_USERNAME/index-life-local.git

# Push to GitHub
git branch -M main
git push -u origin main
```

Replace `YOUR_USERNAME` with your actual GitHub username.

## Step 3: Verify Upload

1. Refresh your GitHub repository page
2. You should see all files uploaded
3. README.md will display automatically

## Step 4: Share with Others

Now anyone can clone and use your application!

### For users to install:

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/index-life-local.git

# Navigate to directory
cd index-life-local

# Install (Windows)
install.bat

# Install (Linux/Mac)
chmod +x install.sh
./install.sh

# Start the application (Windows)
start.bat

# Start the application (Linux/Mac)
chmod +x start.sh
./start.sh
```

## Optional: Add Topics

On your GitHub repository page:

1. Click the ⚙️ gear icon next to "About"
2. Add topics: `diary`, `mood-tracker`, `flask`, `python`, `sqlite`, `privacy`, `local-first`
3. Save changes

## Optional: Create Release

1. Go to repository → Releases → Create a new release
2. Tag version: `v2.0.0`
3. Release title: `v2.0.0 - Initial Local Version`
4. Description:
   ```markdown
   ## index.life Local v2.0.0

   First release of the local-only version of index.life mood diary.

   ### Features
   - 📅 Calendar view with heatmap design
   - ✍️ Daily mood entries (rating + notes)
   - 👤 Profile with photo upload
   - 🔒 100% private - all data stored locally
   - 🚀 Easy installation scripts

   ### Installation

   **Windows:**
   1. Download and extract
   2. Run `install.bat`
   3. Run `start.bat`

   **Linux/Mac:**
   1. Download and extract
   2. Run `./install.sh`
   3. Run `./start.sh`

   **Requirements:**
   - Python 3.8+
   ```
5. Publish release

## Backup Your Data

**IMPORTANT:** The `diary.db` file is in `.gitignore` and will NOT be uploaded to GitHub.

Your personal diary data is saved separately in:
```
f:\index-life-local\diary_with_emile_data_backup.db
```

Keep this file safe! It contains all your mood entries.

## Updating GitHub Repository

When you make changes:

```bash
cd f:\index-life-local

# Check what changed
git status

# Add changes
git add .

# Commit
git commit -m "Description of changes"

# Push to GitHub
git push
```

## Troubleshooting

### Authentication Issues

If GitHub asks for credentials:

**Option 1: Use Personal Access Token**
1. Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate new token
3. Select scopes: `repo`
4. Use token as password when pushing

**Option 2: Use GitHub CLI**
```bash
# Install GitHub CLI from: https://cli.github.com/
gh auth login
```

### Repository Already Exists

If you get "repository already exists" error:

```bash
# Remove old remote
git remote remove origin

# Add correct remote
git remote add origin https://github.com/YOUR_USERNAME/index-life-local.git

# Push
git push -u origin main
```

---

**That's it!** Your project is now on GitHub and ready to share! 🎉
