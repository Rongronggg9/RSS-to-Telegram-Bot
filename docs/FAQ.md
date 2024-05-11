# Frequently Asked Questions

### **Q**: Why some posts were missing? / Why did the bot respond to me so slowly?

**A**: Due to Telegram's restrictions, if too many messages are sent in a short period, the bot will get flood-controlled and have to wait for a certain time. Though the bot will retry, if still gets flood controlled, the message will be dropped. **Avoid subscribing to too many feeds, <ins>especially in channels and groups</ins> (they have a much stricter flood control threshold).**

### **Q**: How to use the bot in my channel or group?

**A**: Just add the bot to your channel or group and send commands. In a channel, "Post Messages" permission is required. If you are an anonymous administrator of a group, the bot needs to be an administrator too (no permission needed) to verify your identity.

### **Q**: The command list in Telegram "Menu" is outdated!

**A**: Send `/lang` and select language again. The bot will update your command list.

### **Q**: How is the performance of the bot?

**A**: The bot is designed to be asynchronous, so it is lightweight and fast. Even if there are over 6000 feeds, the bot can still run on a single core VPS, with an incredibly low load average (~0.2) and approximate 350MB memory usage. The bot can still work fine in such a condition and its stability and usability will not be degraded.

### **Q**: It appears to have a slight memory leak problem...

**A**: It is not a "memory leakage" but a memory fragmentation issue of `glibc`'s `ptmalloc` and not a bug of the bot. It can only be observed on Linux or macOS. Refer to [this issue](https://github.com/kurtmckee/feedparser/issues/287) for possible workarounds. Note that the official Docker image contains some workarounds to get rid of the issue. If you deployed the official Docker image but still find some "memory leakage", please raise an issue.

### **Q**: Why do I still receive notifications even if I mute the subscription?

**A**: "Muted" notification is not aimed to disable the notifications, but to **make the notifications with no sound**. Due to the limitation of Telegram, disabling notifications completely on the sender side is not possible.

### **Q**: I want my bot to serve me only. What should I do?

**A**: Set the env variable `MULTIUSER` to `0`.\
If you need to use the bot in a channel, read the next question.\
Using the bot in a group is possible even if you don't have the multi-user mode enabled, as long as you are a non-anonymous administrator of the group. If you are an anonymous administrator of the group, read the next question.

### **Q**: I want my bot to serve the users/channels/groups I specify only. What should I do?

**A**: Firstly, set the env variable `MULTIUSER` to `0`. This will make guests unable to use the bot.\
If you want to allow a certain user to use the bot, send `/user_info user_id` or `/user_info @username` to the bot and promote their to "User".\
If you want to allow a certain channel/group to use the bot, you should promote both the channel/group itself and at least one of its administrators to "User". Only the promoted administrators can operate the bot in the channel/group.

### **Q**: Why did the bot automatically leave my channel/group?

**A**: Once the bot finds itself lacking the permission to send messages (not granted or being blocked), it will immediately unsubscribe all subscriptions in this chat. Meanwhile, if this chat is a channel or group and the bot is still a member of it, it will leave the channel/group.
Make sure to grant the bot enough permission (sending messages) in channel/group.

A special case is that the bot will leave a topic group if the "General" topic is closed. This is a temporary limitation before topic groups are fully supported.

### **Q**: My bot is not responding. I checked the log and saw Telethon complaining "Server sent a very new message with ID...", "Server replied with a wrong session ID...", or "Could not find a matching Constructor ID for the TLObject...".

**A:** Telethon is protecting you from potential attacks. For details, please refer to [Telethon FAQ](https://docs.telethon.dev/en/stable/quick-references/faq.html#what-does-server-sent-a-very-new-message-with-id-mean). If you believe that it is caused by misconfiguration instead of attacks, and the bot is not deployed on a PaaS platform (e.g. Heroku, Railway), you may stop RSStT, delete the session file (`config/bot.session`), and restart it to solve the problem.
