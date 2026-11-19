"use strict";
// Public pages (open without signing in): About, How it works, FAQ, Privacy, Terms, Contact. Also the shared footer and FAQ block.
const PUBLIC_PAGES = ["about", "how", "faq", "privacy", "terms", "contact"];
const CONTACT_EMAIL = "";   // set an address here to show it on the Contact page
const UPDATED = "19 November 2026";

const FAQ = [
  ["Is it free?", "Yes. Sign in once with Google and every tool is open. There are no ads and nothing to buy."],
  ["Where does the data come from?", "From the public tournament leaderboards that Epic Games publishes for FNCS, Cash Cups and Skin Cups, and from the match replays Epic keeps for recent tournaments. Nothing runs inside your game and no login to your Epic account is needed."],
  ["Can I get banned for using it?", "No. The site never touches the Fortnite client. It only reads public leaderboards and replay files that Epic serves to everyone."],
  ["How accurate are the cutoff predictions?", "The Accuracy page shows the numbers: every finished tournament is predicted as of its start and compared with the real cutoff. Predictions come with a range (Low, Most likely, Safe) because nobody can know a cutoff exactly in advance."],
  ["What is the contest rate?", "For any place on the map, the share of games in which two or more different teams landed there. Players on the same team never count against each other. A high rate means you will probably fight for loot."],
  ["Which tournaments and regions?", "FNCS, Cash Cups, Skin Cups and similar events in NAC, NAW, EU, BR, ASIA, ME and OCE, for Battle Royale, Reload and the other tournament playlists Epic runs."],
  ["Is it affiliated with Epic Games?", "No. FNCS Lab is an unofficial fan project. Fortnite and related names belong to Epic Games."],
];

const faqBlock = (items = FAQ) => `<div class="faq">${items.map(([q, a]) => `<details><summary>${q}</summary><p>${a}</p></details>`).join("")}</div>`;

const pubFoot = () => `<footer class="pubfoot"><div class="pf-brand"><b>FNCS Lab</b><span>Cutoff predictions, drop spots and rotations for Fortnite tournaments.</span></div>
  <nav aria-label="Site"><a href="#/about">About</a><a href="#/how">How it works</a><a href="#/faq">FAQ</a><a href="#/contact">Contact</a><a href="#/privacy">Privacy</a><a href="#/terms">Terms</a></nav>
  <p>Unofficial fan site, not affiliated with Epic Games. Predictions are estimates, not guarantees.</p></footer>`;

const cta = () => sessionOk() ? "" : `<section class="pg-cta"><h2>Try it on your next cup</h2><p>Sign in with Google and the whole site opens.</p><div class="gslot" style="display:flex;justify-content:center;margin-top:18px"></div><p class="small" id="lp-msg" style="margin-top:10px;color:var(--bad)"></p></section>`;

const PAGES = {
  about: ["About FNCS Lab", "A free tool that answers the questions you have during a tournament.", `
    <section><h2>What it is</h2>
    <p>FNCS Lab is a free analysis site for Fortnite competitive tournaments: FNCS, Cash Cups and Skin Cups. It tells you where the cutoff for your goal is likely to land, what a plan for the window looks like, where the teams that qualified dropped, and how they rotated.</p></section>
    <section><h2>Why it exists</h2>
    <p>During a cup you have a few hours, a handful of games and a lot of guessing: do I need a high-elim game now, can I fit another match, is the drop I always take worth it? The answers are in the results of every tournament that came before. This site collects those results and turns them into numbers you can use before you queue.</p></section>
    <section><h2>What is inside</h2><div class="pg-grid">
      <div><b>Live cutoff predictions</b><span>Low, most likely and safe points for any rank from 1 to 10,000, updated while the tournament runs.</span></div>
      <div><b>Strategy plan</b><span>Points to aim for after each game, finisher profiles, pace and a safety margin for your goal.</span></div>
      <div><b>Dropspots</b><span>Heatmaps of where qualifying teams landed, with contest rate, points and best teams for any area you draw.</span></div>
      <div><b>Chest map</b><span>Every chest and container on the map and how often it was opened early.</span></div>
      <div><b>Rotations</b><span>Replay a game's drop and rotations and see where teams stood when each storm circle closed.</span></div>
      <div><b>Accuracy log</b><span>Every prediction is kept and scored against the real result, so you can see how far to trust it.</span></div></div></section>
    <section><h2>How it stays honest</h2>
    <p>Predictions are estimates and the site says so. Where there is not enough history for a mode, it tells you instead of guessing quietly, and the Accuracy page shows the errors, not just the wins. Numbers that are estimated rather than measured are marked.</p></section>
    <section><h2>Not affiliated with Epic Games</h2>
    <p>FNCS Lab is an unofficial fan project. It uses public tournament data and recent public match replays. Fortnite, FNCS and all related names and artwork belong to Epic Games, Inc.</p></section>`],
  how: ["How it works", "Where the numbers come from and what they mean.", `
    <section><h2>1. The data</h2>
    <p>Epic publishes the leaderboard of every tournament window. A collector reads those boards while a window is live (about once a minute) and stores the top 1,000 teams game by game, plus the points at deeper ranks down to 10,000. Finished windows become the history that predictions learn from.</p></section>
    <section><h2>2. Cutoff predictions</h2>
    <p>Before a window starts, the prediction comes from comparable finished events: same gamemode, same format (number of games and scoring), same region first, with newer events counting more. While it runs, the site simulates the field player by player, using what comparable players had at the same moment in past events. The result is shown as three numbers: <b>Low</b> and <b>Safe</b> are the 10th and 90th percentile, <b>Most likely</b> sits between. If you want the cutoff to be safe, aim for the Safe number.</p></section>
    <section><h2>3. Strategy</h2>
    <p>Games left, games that fit in the time you have, and the points per game you would need are worked out from real sequences of past finishers, not an even split. Finishers' points fall with game number, so checkpoints follow what really happened.</p></section>
    <section><h2>4. Dropspots and contest rate</h2>
    <p>Epic keeps a replay of each tournament match for a few weeks. The site reads the first minutes of recent replays to find where each team landed, then matches the teams to the leaderboard to learn how they finished. The <b>contest rate</b> of an area is the share of games with a landing there in which two or more different teams landed there. Teammates never count against each other. Older data that does not record which match a landing belongs to uses an estimate, and says so.</p></section>
    <section><h2>5. Chests and rotations</h2>
    <p>Chest positions are measured from where players stood when they opened them, and the rate is how often one was opened in the first minutes. Rotations come from full replays: where a team was when each storm circle started closing, and whether it was outside when it closed.</p></section>
    <section><h2>Limits</h2>
    <p>Epic's endpoints are unofficial and can change. Only the top 1,000 teams of each window are stored in full. Replays are deleted after a few weeks, so landing data only exists for recent tournaments. Predictions are estimates, not guarantees.</p></section>`],
  faq: ["Frequently asked questions", "Short answers.", `<section>${faqBlock()}</section>`],
  contact: ["Contact", "Questions, bugs, ideas, or a request to delete your data.", `
    <section><h2>Get in touch</h2>
    ${CONTACT_EMAIL ? `<p>Email <a href="mailto:${CONTACT_EMAIL}">${CONTACT_EMAIL}</a>.</p>` : `<p>Once you are signed in, use <b>Send feedback</b> at the bottom of the left menu. It reaches the owner directly and is the quickest way to report a bug, ask for a feature, or ask for your data to be removed.</p>`}</section>
    <section><h2>Reporting a wrong number</h2><p>Tell us the tournament, the region and what looked wrong. Predictions that missed badly are always worth a look.</p></section>`],
  privacy: ["Privacy policy", "Last updated " + UPDATED + ".", `
    <section><h2>What we collect</h2>
    <p>When you sign in with Google we receive your Google account identifier, name, email address, and profile picture URL. We store the identifier, name, email address and the times you first and last signed in, so the owner can see how many people use the site. We do not receive your Google password.</p>
    <p>If you look yourself up by Epic name, the site searches Epic's <b>public</b> tournament leaderboards for that name. We do not ask for your Epic login and cannot see anything private on your Epic account. Your saved Epic name stays in your browser.</p></section>
    <section><h2>What is kept in your browser</h2>
    <p>Your sign-in token (valid for 30 days), theme, region and similar settings are kept in your browser's local storage. The site sets no tracking or advertising cookies. Signing out removes the token.</p></section>
    <section><h2>How we use it</h2>
    <p>Only to let you sign in, to keep the tools behind a sign-in, and to understand how much the site is used. We do not sell your data, share it with advertisers, or use it to send marketing email.</p></section>
    <section><h2>Services we rely on</h2>
    <p>Google (sign-in), Vercel (hosting) and Neon (database). They process data on our behalf under their own terms. Tournament data comes from Epic Games' public endpoints.</p></section>
    <section><h2>Your choices</h2>
    <p>You can sign out at any time, clear the site's local storage in your browser, or ask for your stored sign-in record to be deleted through the <a href="#/contact">Contact</a> page. You can also remove the site's access to your Google account at <b>myaccount.google.com/permissions</b>.</p></section>
    <section><h2>Changes</h2><p>If this policy changes, the date above changes with it.</p></section>`],
  terms: ["Terms of use", "Last updated " + UPDATED + ".", `
    <section><h2>Using the site</h2>
    <p>FNCS Lab is a free fan project provided as is. You may use it for personal, non-commercial purposes. Do not try to break it, overload it, scrape it in bulk, or bypass the sign-in.</p></section>
    <section><h2>Estimates, not promises</h2>
    <p>Predictions, plans and statistics are estimates built from past results. They can be wrong and nothing on the site guarantees a result in any tournament. You use them at your own risk.</p></section>
    <section><h2>Not affiliated</h2>
    <p>The site is unofficial and not affiliated with, endorsed by or sponsored by Epic Games, Inc. Fortnite and related names and artwork belong to Epic Games. Tournament data is read from Epic's public services and may change or stop at any time.</p></section>
    <section><h2>Availability</h2>
    <p>The site may change, be interrupted or be withdrawn at any time. Access can be removed for misuse.</p></section>
    <section><h2>Your data</h2><p>See the <a href="#/privacy">privacy policy</a>.</p></section>`],
};

function publicPage(p) {
  destroyCharts();
  const [title, sub, body] = PAGES[p] || PAGES.about;
  document.title = title + " · FNCS Lab";
  app.innerHTML = `<div class="pg"><a class="pg-back" href="#/">← ${sessionOk() ? "Home" : "FNCS Lab"}</a><h1>${title}</h1><p class="pg-sub">${sub}</p>${body}${cta()}${pubFoot()}</div>`;
  googleSlots();
}

// the nav shown above the signed-out pages: scrolls to a part of the home page or opens a public page
document.addEventListener("click", e => {
  const a = e.target.closest("[data-scroll]"); if (!a) return;
  e.preventDefault();
  const go = () => { const t = document.getElementById(a.dataset.scroll); if (t) t.scrollIntoView({ behavior: "smooth", block: "start" }); else window.scrollTo({ top: 0, behavior: "smooth" }); };
  if (location.hash && location.hash !== "#/" && location.hash !== "#") { location.hash = "#/"; setTimeout(go, 80); } else go();
});
