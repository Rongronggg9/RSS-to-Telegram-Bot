# Migration Guide (to v2)

## Docker / Docker Compose / Dirty run

1. **Turn to your bot. Send `/export` to back up your subscriptions.**
1. (Optional) Back up your `/path/to/bot/config/`.
1. Delete `/path/to/bot/config/`.
1. [Redeploy](deployment-guide.md) your bot cleanly. Configure [other variables](advanced-settings.md) as you need.
1. Turn to your bot. Send `/import` to import your subscriptions again.

## Railway.app

1. **Turn to your bot. Send `/export` to back up your subscriptions.**
1. Turn to your Railway project.
1. (Optional) Back up your Redis database if you know how to do it.
1. Turn to the `Settings` page, switch to the `Danger` tab. `Remove` the Redis plugin.
1. Click the `Add Plugin` button on the bottom left, select `Add PostgreSQL`.
1. Turn to the `Variables` page. `Delete` the `CHATID` and `DELAY` variables. Configure [other variables](advanced-settings.md) as you need.
1. Turn to your forked GitHub repository. Switch to the branch you've deployed, then click `Fetch upstream` and `Fetch and merge`.
1. Wait for your Railway project to be updated.
1. Turn to your bot. Send `/import` to import your subscriptions again.

## If you're using the `multiuser` branch...

Make sure you switch to the `master` or `dev` branch. For Railway, you can do this by switching the deployment triggers (`Deployments` -> `Triggers` -> `Branches` -> add a new trigger and delete the old one) **BEFORE START MIGRATING ACCORDING TO THE GUIDE**.

## If you still would like to limit the bot to serve you only...

Set the env variable `MULTIUSER` to `0`.  
However, if you need to use the bot in a channel, you cannot switch off the multi-user mode for the moment. As a temporary workaround, you may first switch on the multi-user mode, subscribe to the feeds you like in your channel, and then switch off the multi-user mode.  
Using the bot in a group is possible even if you don't have the multi-user mode enabled, as long as you are an administrator of the group. [Make sure that the bot can identify you](FAQ.md#q-how-to-use-the-bot-in-my-channel-or-group), especially if you are an anonymous administrator of the group.
