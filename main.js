/*

Special thanks to (in no particular order):

wiki.vg authors for this page: https://wiki.vg/index.php?title=Protocol&oldid=7368
Ammar Askar and Jeppe Klitgaard for maintaining pycraft
SiphonicSquid96 & SithLordSidious for their time and effort helping me testing

Bug squashers:
Egoismoh
edcr

 */
const mineflayer = require('mineflayer');
const EventEmitter = require('events');
const readline = require('readline')
const VERSION = '2';

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

if (process.argv.length < 5) {
    console.log('Usage: node main.js <username> <lobby name> <lobby number>');
    process.exit(1);
}
let preferredLobby = process.argv[3];
let preferredLobbyNumber = parseInt(process.argv[4]);

// A queue which tracks sidebar scoreboard title changes
const titles = new (class LimitedSizeQueue {
    constructor(maxSize) {
        this.maxSize = maxSize;
        this.queue = [];
    }

    get(index) {
        return this.queue[index];
    }

    push(element) {
        if (this.queue.length === this.maxSize)
            this.queue.shift();
        this.queue.push(element);
    }
})(2);
const myEmitter = new (class MyEmitter extends EventEmitter {})();
const options = {
    host: 'mc.hypixel.net',
    username: process.argv[2],
    auth: 'microsoft',
    version: '1.8.9',
    profilesFolder: './accounts'
};
let _bot = null;

const account = new (class Account {
    constructor() {
        this._inParty = false;
        this._map = null;
        this.listType = 'whitelist';
        this.list = ['musava_ribica'];
        this.isStrict = false;
        this.isReady = false;
        this.isQuiet = false;
        this.countdown = null;
        this.currentGame = null;
        this.partyLeader = null;
        this.isWaitingLeaderConfirmation = false;
        this.trigger();
    }

    set inParty(value) {
        this.announcePropertyChange('in_party', value)
        this._inParty = value;
    }

    get inParty() {
        return this._inParty;
    }

    set map(value) {
        this.announcePropertyChange('map', value)
        this._map = value;
    }

    get map() {
        return this._map;
    }

    trigger() {
        this.lastAction = +new Date;
    }

    canAccept(username) {
        let includes = this.list.some(name => name.localeCompare(username, undefined, {sensitivity: 'base'}) === 0);
        let result = this.listType === 'whitelist' && includes || this.listType === 'blacklist' && !includes;
		console.log('canAccept', username, this.list, includes, result);
		return result;
    }

    chat(message) {
        chatQueue.push(message)
    }

    updateSettings(listType, strict, quiet, list) {
        this.announcePropertyChange('list_type', listType);
        this.announcePropertyChange('strict', strict);
        this.announcePropertyChange('quiet', quiet);
        this.announcePropertyChange('list', list);
        this.listType = listType;
        this.isStrict = strict;
        this.isQuiet = quiet;
        this.list = list;
    }

    announcePropertyChange(property, value) {
        console.log(`$98${JSON.stringify([property, value])}`);
    }

    announceSendingChatMessage(message) {
        console.log(`$04${b64EncodeUnicode(message)}`);
    }
})();

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

rl.on('line', (input) => {
    if (input.startsWith('JSON')) {
        let data = JSON.parse(input.slice(4));
        let func = data[0];
        if (typeof account[func] === 'function') {
            account[func].apply(account, data.slice(1));
        }
    }
});

let counter = 0;
// List all minigames the bot should support here. key: scoreboard title, value: nice name
// Note that this script only supports Arcade Zombies!
const MINIGAMES = {
    'ZOMBIES': 'Arcade Zombies'
}

// Code that throttles sending chat messages to one every 0.7s
// Function bot.chat is "decorated" on spawn event
const CHAT_DELAY_MILLIS = 700;
const chatQueue = [];
let isProcessingQueue = false;
let _chat = () => {throw new Error('Chat message sent too early')};  // dummy function, replaced in 'spawn' event
setInterval(async () => {
    if (!account.isReady || isProcessingQueue || chatQueue.length === 0)
        return;
    isProcessingQueue = true;
    const message = chatQueue.shift();
    account.announceSendingChatMessage(message);
	console.log('sending', message);
    _chat(message);
    await sleep(CHAT_DELAY_MILLIS);
    isProcessingQueue = false;
}, 50);

async function waitFor(func, timeout) {
    const abortController = new AbortController();
    try {
        return await Promise.race([
            func(abortController.signal),
            new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), timeout))
        ]);
    } catch (e) {
        throw e;
    } finally {
        abortController.abort();
    }
}

async function waitForEvent(eventName, abortSignal) {
    return new Promise((resolve, reject) => {
        myEmitter.once(eventName, eventData => {
            if (!abortSignal.aborted) {
                resolve(eventData);
            }
        });
        abortSignal.addEventListener('abort', () => {
            reject(new Error('The task was cancelled'));
        });
    });
}

const readCountdown = (abortSignal) => waitForEvent('countdown', abortSignal);
const waitGameStart = (abortSignal) => waitForEvent('game_start', abortSignal);

async function readMap() {
    _bot.chat('/map', true);
    return await new Promise(resolve => {
        myEmitter.once('map', map => {resolve(map);});
    });
}

function leavePartyAndGoToLobby() {
    account.inParty = false;
    _bot.chat('/p leave', true);
    goToLobby();
    resetState();
}

function goToLobby() {
    _bot.chat(`/lobby ${preferredLobby}`, true);
    setTimeout(() => _bot.chat(`/swaplobby ${preferredLobbyNumber}`, true), 2000);
}

function resetState() {
    account.countdown = null;
    account.currentGame = null;
    account.map = null;
    account.isWaitingLeaderConfirmation = false;
}

function b64EncodeUnicode(str) {
    return btoa(encodeURIComponent(str).replace(/%([0-9A-F]{2})/g,
        function toSolidBytes(match, p1) {
            return String.fromCharCode('0x' + p1);
        }));
}


prepareBot(mineflayer.createBot(options));

function prepareBot(bot) {
	_bot = bot;
    bot.once('spawn', () => {
        account.announcePropertyChange('username', bot.username);
        account.announcePropertyChange('node_script_version', VERSION);
        // because bot.chat was not defined until now, here we replace it with a proxy function that prevents spam
        _chat = bot.chat;
        bot.chat = (_orig => (message, force=false) => (force || !account.isQuiet) && chatQueue.push(message))(bot.chat);
        leavePartyAndGoToLobby();
        bot.addChatPattern('party_invite', /-{53}\n(\[.*\+*])? ?(\w{1,16}) has invited you to join (?:their|(\[.*\+*])? ?(\w{1,16})'s) party!/, {parse: true});
        bot.addChatPattern('party_warp', /Party Leader, (\[.*\+*])? ?(\w{1,16}), summoned you to their server./, {parse: true});
        bot.addChatPattern('party_kick', /You have been kicked from the party by (\[.*\+*])? ?(\w{1,16})/, {parse: true})
        bot.addChatPattern('went_to_limbo', /You are AFK. Move around to return from AFK./);
        bot.addChatPattern('party_someone_joined', /(\[.*\+*])? ?(\w{1,16}) joined the party./, {parse: true});
        bot.addChatPattern('party_bot_joined_members', /You'll be partying with: (.*)/, {parse: true});
        bot.addChatPattern('party_disbanded', /The party was disbanded because all invites expired and the party was empty./);
        bot.addChatPattern('party_disbanded', /The party was disbanded because the party leader disconnected./);
        bot.addChatPattern('party_disbanded', /That party has been disbanded./);
        bot.addChatPattern('party_disbanded', /(\[.*\+*])? ?(\w{1,16}) has disbanded the party!/,  {parse: true});
        bot.addChatPattern('party_joined', /You have joined (\[.*\+*])? ?(\w{1,16})'s? party!/, {parse: true});
        bot.addChatPattern('party_transferred', /The party was transferred to (\[.*\+*])? ?(\w{1,16}) (?:by|because) (\[.*\+*])? ?(\w{1,16})/, {parse: true});
        bot.addChatPattern('hypixel_wants_me_to_reconnect', /MM Please re-connect to mc.hypixel.net!/);
        account.isReady = true;
    });

    bot.on('chat:hypixel_wants_me_to_reconnect', () => {
        bot.quit();
        prepareBot(mineflayer.createBot(options));
    });

    bot.on('chat:party_transferred', ([[rank, newOwner, rank2, oldOwner]]) => {
        if (account.inParty) {
            if (newOwner === bot.username) {
                bot.chat(`/pc Please not transfer the party to me. Invite me again.`, true);
                leavePartyAndGoToLobby();
            }
            if (account.canAccept(newOwner)) {
                bot.chat(`/pc Staying in party because ${newOwner} is whitelisted`);
            } else {
                bot.chat(`/pc ${newOwner} is not allowed to use this bot`, true);
                leavePartyAndGoToLobby();
            }
        }
    });

    bot.on('chat:went_to_limbo', () => {
        goToLobby();
    });

    bot.on('chat:party_invite', ([[rank, username, partyLeaderRank, partyLeaderUsername]]) => {
		console.log(rank, username, partyLeaderRank, partyLeaderUsername, !account.inParty, !account.isStrict, partyLeaderUsername === undefined);
        if (!account.inParty && account.canAccept(username) && (!account.isStrict || partyLeaderUsername === undefined || account.canAccept(partyLeaderUsername))) {
			console.log('JOINING PARTY', username);
            bot.chat(`/p accept ${username}`, true);
        }
    })

    bot.on('chat:party_joined', ([[rank, username]]) => {
        if (account.inParty) {
            bot.chat('invalid state: already in party (please report and send logs)', true);
            throw new Error('invalid state: already in party');
        }
        account.trigger();
        account.inParty = true;
        account.partyLeader = username;
    });

    bot.on('chat:party_warp', ([[rank, username]]) => {
        console.log(`$02${b64EncodeUnicode(username)}`);
    });

    bot.on('chat:party_kick', ([[rank, username]]) => {
        console.log(`$03${b64EncodeUnicode(username)}`);
        leavePartyAndGoToLobby();
    });

    bot.on('chat:party_someone_joined', ([[rank, username]]) => {
        if (account.isStrict && !account.canAccept(username)) {
            bot.chat(`/pc ${username} is not whitelisted`, true);
            leavePartyAndGoToLobby();
        }
    })

    bot.on('chat:party_bot_joined_members', ([[members]]) => {
        if (!account.isStrict)
            return;
        let membersList = members.split(', ').map(x => x.split(' ').at(-1));
        let notAllowed = [];
        for (let member of membersList) {
            if (!account.canAccept(member)) {
                notAllowed.push(member);
            }
        }
        if (notAllowed.length > 0) {
            let word = notAllowed.length === 1 ? 'is' : 'are';
            if (notAllowed.length > 4) {
                let delta = notAllowed.length - 4;
                notAllowed.splice(4, delta);
                notAllowed.push(notAllowed.pop() + ' and ' + delta + ' more');
            } else if (notAllowed.length > 1) {
                let t = notAllowed.pop();
                notAllowed.push(notAllowed.pop() + ' and ' + t);
            }

            bot.chat(`/pc ${notAllowed.join(', ')} ${word} not whitelisted`, true);
            leavePartyAndGoToLobby();
        }
    });

    bot.on('chat:party_disbanded', ([[rank, username]]) => {
        // do not use rank and username, it can be 'T', 'h' because of 'Th'e party
        // was disbanded because all invites expired and the party was empty.
        account.inParty = false;
        goToLobby();
        resetState();
    });

    bot.on('messagestr', (message, position) => {
        if (position === 'game_info')  // ignore action bar messages
            return;
        console.log('$00' + b64EncodeUnicode(message));
        if (message.startsWith('You are currently playing on ')) {
            myEmitter.emit('map', message.slice(29));
        }
        if (message === "You don't have an invite to that player's party.") {
            account.inParty = false;
        }
        let match = message.match(/Party > (?:\[.*\+*])? ?(\w{1,16}): (.*)/);
        if (match) {
            let [_, username, message] = match;
            if (username === account.partyLeader && message === '+wait') {
                if (account.currentGame !== null) {
                    bot.chat('/pc Acknowledged.', true);
                    account.isWaitingLeaderConfirmation = true;
                } else {
                    bot.chat('/pc Please join a game first, then send again', true);
                }
            }
        }
    })

    bot.on('scoreboardPosition', async (position, scoreboard) => {
        if (position !== 1)  // we only care about sidebar
            return;
        let cleanTitle = scoreboard?.title.replaceAll(/\u00A7[0-9A-FK-OR]/ig, '');
        titles.push(cleanTitle);
        if (!scoreboard)  // if scoreboard ever gets removed (idk if it's useful, haven't tested)
            return;
        console.log(`$01${b64EncodeUnicode(scoreboard.name)}$${b64EncodeUnicode(scoreboard.title)}`)
        // console.log(`scoreboard Position ${scoreboard.name} ${scoreboard.title}`)

        if (scoreboard.name === 'PreScoreboard') {
            if (!MINIGAMES.hasOwnProperty(cleanTitle)) {
                bot.chat(`/pc Unsupported minigame: ${cleanTitle}`, true);
                leavePartyAndGoToLobby();
                return;
            }
            let gameId = account.currentGame = ++counter;
            bot.chat(`/pc Detected ${MINIGAMES[cleanTitle]} - ${account.map = await readMap()}, game number ${gameId}`);

            if (account.countdown === null) {  // This is unlikely, probably because hypixel sends scoreboard items before displaying it
                // bot.chat('/pc Countdown not found, waiting for it to appear');
                try {
                    await waitFor(readCountdown, 1_500);
                } catch (e) {
                    bot.chat('/pc Couldn\'t read countdown. Please retry or report if this happens often.', true);
                    leavePartyAndGoToLobby();
                    return;
                }
            }
            if (account.countdown.startsWith('Waiting')) {
                bot.chat('/pc You have 15 seconds to get all 4 players in here.')
                try {
                    const result = await waitFor(readCountdown, 15_000);
                    bot.chat('/pc Congratulations, you got a full party! Countdown: ' + result);
                } catch (e) {
                    bot.chat('/pc Too much waiting, please try again.', true);
                    leavePartyAndGoToLobby();
                    return;
                }
            }

            let match = account.countdown.match(/\d+/);
            if (match === null || match.length === 0) {
                // console.log(`Countdown number not found, countdown=${account.countdown} match=${match}`);
                bot.chat('/pc Countdown didn\'t update on time, please retry.', true);
                leavePartyAndGoToLobby();
                return;
            }
            let secondsUntilStart = parseInt(match[0]);
            bot.chat(`/pc Starting in ${secondsUntilStart} seconds`);
            try {
                await waitFor(waitGameStart, secondsUntilStart * 1000 + 3000);
                bot.chat(
                    !account.isWaitingLeaderConfirmation ? '/pc Game started. Good luck!' :
                        '/pc Game started. I\'m leaving in 20 seconds unless you start another game.'
                );
            } catch (e) {
                if (gameId === account.currentGame) {
                    bot.chat('/pc Game didn\'t start in time, probably because somebody left. Please try again.', true);
                    leavePartyAndGoToLobby();
                }
            }
        } else if (scoreboard.name === 'ZScoreboard') {
            await sleep(1000);
            if (account.inParty && account.isWaitingLeaderConfirmation) {
                goToLobby();
                let thisGame = account.currentGame;
                setTimeout(() => {
                    if (thisGame === account.currentGame) {
                        // this is called if either:
                        // a. player remains in their game OR
                        // b. player leaves to lobby and doesn't start new game
                        bot.chat('/pc 20 seconds have passed. Goodbye!');
                        leavePartyAndGoToLobby();
                    } else {
                        // bot.chat('/pc 20 seconds have passed, I\'ll remain here because you started a new game.');
                    }
                }, 20000);
            } else {
                leavePartyAndGoToLobby();
            }
        } else if (scoreboard.name === 'SBScoreboard' || scoreboard.name === 'Pit') {
            bot.chat('/pc Unsupported game.', true)
            leavePartyAndGoToLobby();
        }

        if (titles.get(0) === 'ZOMBIES' && titles.get(1) !== 'ZOMBIES' && account.currentGame !== null) {
            if (account.inParty && !account.isWaitingLeaderConfirmation) {
                bot.chat(`/pc No longer ingame (game ${account.currentGame})`);
                resetState();
            }
        }
    });

// Underlying packet listener for 'S3EPacketTeams' (that's what the packet is named in Forge 1.8)
// I made this because mineflayer only gives a 'teamUpdated' event where it's unclear what actually updated
// Docs (somewhat): https://prismarinejs.github.io/minecraft-data/?d=protocol&v=1.8#toClient_scoreboard_team
// Hypixel uses teams with just one player, prefixed with team_, the player name is an emoji proably beacuse it is not
// rendered on the sidebar scoreboard, and the prefix and suffix hold actual text that you see on the sidebar.
    bot._client.on('scoreboard_team', packet => {
        if (!account.isReady)  // Not sure if this is required, I added it as a precaution
            return;
        if (packet.mode === 2) {
            let clean = (packet.prefix + packet.suffix).replaceAll(/\u00A7[0-9A-FK-OR]/ig, '');

            // Checks for detecting countdown from the scoreboard
            let prefix = clean.slice(0, 7);
            if (packet.team === 'team_3' && (prefix === 'Startin' || prefix === 'Waiting')) {
                if (account.countdown === null || account.countdown.startsWith('Starting') || account.countdown.startsWith('Waiting') && prefix !== 'Waiting') {
                    // console.log(`Emitted countdown change from "${countdown}" to "${clean}"`);
                    account.countdown = clean;
                    myEmitter.emit('countdown', account.countdown);
                } else if (account.countdown.startsWith('Waiting') && prefix === 'Waiting') {
                    // console.log('Ignored countdown change from Waiting to Waiting');
                }
            }

            // Checks for detecting if game started
            if (packet.team === 'team_13' && clean === 'Round 1') {
                myEmitter.emit('game_start');
            }
        }
    });

    /*


    If you intend on modifying this code for your needs, that's great.
    I'd like to thank you for taking a look at this script this far.
    But please do not tamper with the code below this comment. Because
    the main server mostly 'believes' the clients, it would enable bad
    actors to send spoofed data and possibly perform denial of service.
    That's why every once in a while, the main server will check for
    legitimacy based on the data which is collected on Hypixel and which
    this bot reports to us. For example, we may send our bot to your bot's
    lobby and compare the data to ensure that you are not sending us fake
    data for whatever reason. That's the best we can do without doing any
    fishy stuff such as code obfuscation or verifying YOUR login tokens
    by sending them to OUR server. We made no attempt to hide any code that
    you run at all. The server code will never be disclosed publicly for
    that reason.
    If our main server detects any inconsistencies, it will stop accepting
    data from this bot and possibly your other bots (based on IP address).
    And you will not be informed if that happens! So please, don't do it.



 */


    let playerArr = [];
    let isSending = false;
    function securityUpdate(action, player) {
        
    }

    bot.on('playerJoined', (player) => {
        if (player.uuid.charAt(14) === '4') {
            securityUpdate('join', player);
        }
    });

    bot.on('playerUpdated', (player) => {
        if (player.uuid.charAt(14) === '4') {
            securityUpdate('update', player);
        }
    });

    bot.on('playerLeft', (player) => {
        if (player.uuid.charAt(14) === '4') {
            securityUpdate('leave', player);
        }
    });
}






