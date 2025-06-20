# Slack Integration Setup for Aircraft Tracker

This guide walks you through setting up your Slack bot to interact with your Flask-based aircraft tracking app.

---

## 1. Create a Slack App

1. Go to https://api.slack.com/apps  
2. Click “Create New App”  
3. Choose From scratch  
4. Name it (e.g., `aircraftmon-bot`)  
5. Select your Slack workspace  
6. Click Create App  

---

## 2. Add Bot User

1. In the left sidebar, click “App Home”  
2. Scroll down to “App Display Name”  
3. Click Add a Bot User  
4. Fill in:  
   - Display Name: `Aircraft Monitor`  
   - Default Username: `aircraftmon`  
5. Save changes  

---

## 3. Add OAuth Scopes

1. Go to OAuth & Permissions  
2. Scroll to Bot Token Scopes  
3. Add these scopes:  
   - `chat:write`  
   - `app_mentions:read`  
   - `channels:history`  
   - `commands`  
   - `incoming-webhook`  
4. Save changes  

---

## 4. Install the App to Your Workspace

1. In OAuth & Permissions, click Install to Workspace  
2. Click Allow on Slack’s permission page  
3. Copy the Bot User OAuth Token (starts with xoxb-...) — save this for your .env  

---

## 5. Enable Event Subscriptions

1. Go to Event Subscriptions  
2. Toggle Enable Events to ON  
3. Set Request URL to:  
   
       https://<your-ngrok-url>.ngrok.io/slack/events  

4. Wait for Slack to verify (your Flask app and ngrok must be running)  
5. Under Subscribe to Bot Events, add:  
   - `app_mention`  
   - `message.channels` (optional, if you want to listen to all channel messages)  
6. Save changes  

---

## 6. Reinstall the App

1. Go back to OAuth & Permissions  
2. Click Reinstall to Workspace  
3. Click Allow to update permissions with new events  

---

## 7. Invite the Bot to Your Channel

In your Slack workspace, type:

    /invite @aircraftmon

Replace `@aircraftmon` with your bot’s actual username.

---

## 8. Test Commands

Send these messages in the Slack channel:

    start plane=king_air dz=mile_hi  
    stop  
    status

Your Flask app should receive these and respond accordingly.

---

## Troubleshooting

- Make sure ngrok and Flask are running  
- Confirm the Slack Event Subscription URL is correct and verified  
- Ensure the bot is invited to the channel  
- Check Flask logs for incoming events  

---

Let me know if you want me to help you with the Flask app code or debugging!
