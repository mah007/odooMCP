# Odoo MCP Server - Enhanced Edition

## 🎉 What You Have Downloaded

This is the **production-ready, enhanced version** of the vzeman/odoo-mcp-server, specifically optimized for n8n AI Agents, ChatGPT, and Gemini.

## ✅ What's Fixed

1. **JSON Schema Validation** - Resolves the "Invalid schema for function 'execute_method'" error in n8n
2. **Missing Service Methods** - All tools now work without AttributeError
3. **API Key Authentication** - Secure your Odoo data from unauthorized access

## 📦 Package Contents

```
odoo-mcp-fixed/
├── DEPLOYMENT_GUIDE.md    # Complete deployment instructions
├── CHANGES.md              # Detailed changelog
├── deploy.sh               # Automated deployment script
├── mcp_server_odoo/        # Enhanced server code
│   ├── http_server.py      # ✅ Schema fixes + API auth
│   ├── config.py           # ✅ API key configuration
│   └── services/
│       └── odoo_service.py # ✅ Missing methods added
└── ... (other files)
```

## 🚀 Quick Start

### 1. Extract the Archive

```bash
tar -xzf odoo-mcp-server-enhanced.tar.gz
# OR
unzip odoo-mcp-server-enhanced.zip
```

### 2. Upload to Your Server

```bash
# Upload the odoo-mcp-fixed directory to your server
scp -r odoo-mcp-fixed/ user@your-server:/path/to/deployment/
```

### 3. Deploy

```bash
# On your server
cd /path/to/deployment/odoo-mcp-fixed
chmod +x deploy.sh
./deploy.sh
```

The deployment script will:
- ✅ Check Docker installation
- ✅ Create a template .env file (if needed)
- ✅ Build and start the Docker container
- ✅ Run health checks
- ✅ Provide next steps for n8n integration

### 4. Configure n8n

In your n8n MCP Client node:
- **Endpoint URL:** `http://your-server:8000`
- **Authentication:** Header Auth
  - **Header Name:** `X-API-Key`
  - **Header Value:** (the value from your `MCP_API_KEY` environment variable)

## 📚 Documentation

- **DEPLOYMENT_GUIDE.md** - Complete deployment and integration guide
- **CHANGES.md** - Detailed changelog of all fixes and enhancements

## 🔒 Security

This enhanced version includes API Key authentication. **Always set a strong `MCP_API_KEY`** in production:

```bash
# Generate a strong API key
openssl rand -hex 32
```

Add it to your `.env` file:
```bash
MCP_API_KEY=your_generated_key_here
```

## 🆘 Support

If you encounter issues:
1. Check the **DEPLOYMENT_GUIDE.md** troubleshooting section
2. Review Docker logs: `docker logs mcp-server`
3. Verify your `.env` configuration

## 📝 Credits

- **Original Repository:** https://github.com/vzeman/odoo-mcp-server
- **Enhanced By:** Manus AI Agent
- **Date:** November 22, 2025

## 📄 License

Same as the original repository (vzeman/odoo-mcp-server)

---

**Version:** 1.0.0-enhanced  
**Compatibility:** n8n, ChatGPT, Gemini, Claude (via n8n)
