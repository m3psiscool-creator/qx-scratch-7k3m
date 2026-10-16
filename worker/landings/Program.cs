// Reads tournament replays and prints where every player landed.
//   landings <file.replay> [more files...]      -> one JSON object per line
// Landing = the first moment after leaving the battle bus that the player is on the ground (vertical speed exactly 0).
using System.Globalization;
using System.Text;
using FortniteReplayReader;
using Unreal.Core;
using Unreal.Core.Models;
using Unreal.Core.Models.Enums;

var inv = CultureInfo.InvariantCulture;
const int MaxChestItems = 9;   // chests give about 5 items; player death drops are mostly 9+

foreach (var file in args)
{
    var sb = new StringBuilder();
    try
    {
        var reader = new Spy();
        var replay = reader.ReadReplay(file);
        var g = replay.GameData;
        sb.Append("{\"file\":").Append(Q(Path.GetFileName(file)))
          .Append(",\"playlist\":").Append(Q(g.CurrentPlaylist))
          .Append(",\"players\":[");
        bool first = true;
        var trail = new List<(double x, double y)>();
        var deaths = new List<(double x, double y, double t)>();
        foreach (var p in replay.PlayerData.Where(p => !p.IsBot && p.Locations.Count > 5))
        {
            var L = p.Locations.Where(m => m.ReplicatedMovement.HasValue).ToList();
            double T(int i) => L[i].ReplicatedWorldTimeSecondsDouble ?? L[i].LastUpdateTime ?? 0;
            var P = (Func<int, Unreal.Core.Models.FVector>)(i => L[i].ReplicatedMovement.Value.Location);
            // leaving the bus: flag when the replay has it, else the first time far above the island
            int exit = -1;
            for (int i = 0; i < L.Count && exit < 0; i++)
                if (L[i].bIsSkydivingFromBus == true || P(i).Z > 30000) exit = i;
            int land = -1;
            if (exit >= 0)
                for (int i = exit + 1; i < L.Count; i++)
                {
                    var r = L[i].ReplicatedMovement.Value;
                    if (T(i) - T(exit) > 6 && P(i).Z < 8000 && Math.Abs(r.LinearVelocity.Z) < 1 && Math.Abs(P(i).Z - P(i - 1).Z) < 400) { land = i; break; }
                }
            // ground traffic for the map background: one point every ~4 seconds once on the ground
            if (land >= 0)
            {
                double last = -999;
                for (int i = land; i < L.Count; i++)
                    if (P(i).Z < 9000 && T(i) - last >= 4) { last = T(i); trail.Add((P(i).X, P(i).Y)); }
            }
            if (!first) sb.Append(',');
            first = false;
            sb.Append("{\"epic\":").Append(Q(p.EpicId)).Append(",\"team\":").Append(p.TeamIndex?.ToString(inv) ?? "null")
              .Append(",\"placement\":").Append(p.Placement?.ToString(inv) ?? "null")
              .Append(",\"kills\":").Append(p.Kills?.ToString(inv) ?? "null");
            if (p.DeathLocation != null)   // where and when (game clock) this player was eliminated
                deaths.Add((p.DeathLocation.X, p.DeathLocation.Y, p.DeathTimeDouble ?? p.DeathTime ?? 0));
            if (p.DeathLocation != null)
                sb.Append(",\"death\":[").Append(p.DeathLocation.X.ToString("F0", inv)).Append(',').Append(p.DeathLocation.Y.ToString("F0", inv)).Append(',')
                  .Append((p.DeathTimeDouble ?? p.DeathTime ?? 0).ToString("F1", inv)).Append(']');
            if (land >= 0)
            {
                var lp = P(land);
                sb.Append(",\"x\":").Append(lp.X.ToString("F0", inv)).Append(",\"y\":").Append(lp.Y.ToString("F0", inv))
                  .Append(",\"z\":").Append(lp.Z.ToString("F0", inv))
                  .Append(",\"t_exit\":").Append(T(exit).ToString("F1", inv)).Append(",\"t_land\":").Append(T(land).ToString("F1", inv));
            }
            sb.Append('}');
        }
        sb.Append("],\"trail\":[");
        for (int i = 0; i < trail.Count; i++)
        {
            if (i > 0) sb.Append(',');
            sb.Append('[').Append(trail[i].x.ToString("F0", inv)).Append(',').Append(trail[i].y.ToString("F0", inv)).Append(']');
        }
        sb.Append("],\"clock_offset\":").Append(reader.ClockOffset.ToString("F2", inv)).Append(",\"chests\":[");
        // A player's elimination drops their whole inventory at once, which looks like a chest. Remove every burst that is at a
        // death place around the death moment (game clock = replay time + offset), and any burst too big to be a chest.
        var off = reader.ClockOffset;
        var bursts = reader.Bursts().Where(b => b.n <= MaxChestItems
            && !deaths.Any(d => Math.Sqrt(Math.Pow(b.x - d.x, 2) + Math.Pow(b.y - d.y, 2)) <= 600 && Math.Abs(d.t - (b.t + off)) <= 4)).ToList();
        for (int i = 0; i < bursts.Count; i++)
        {
            if (i > 0) sb.Append(',');
            sb.Append('[').Append(bursts[i].x.ToString("F0", inv)).Append(',').Append(bursts[i].y.ToString("F0", inv)).Append(',')
              .Append(bursts[i].n).Append(',').Append(bursts[i].t.ToString("F0", inv)).Append(']');
        }
        sb.Append("],\"containers\":[");
        int ci = 0;
        foreach (var kv in reader.Opened)
        {
            if (ci++ > 0) sb.Append(',');
            sb.Append('[').Append(Q(kv.Key)).Append(',').Append(kv.Value.x.ToString("F0", inv)).Append(',').Append(kv.Value.y.ToString("F0", inv)).Append(',').Append(kv.Value.t.ToString("F0", inv)).Append(']');
        }
        sb.Append("]}");
    }
    catch (Exception e)
    {
        sb.Clear();
        sb.Append("{\"file\":").Append(Q(Path.GetFileName(file))).Append(",\"error\":").Append(Q(e.Message)).Append('}');
    }
    Console.WriteLine(sb.ToString());
}

static string Q(string s) => s == null ? "null" : "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";

// Loot pickups (FortPickupAthena) with the time and place they appeared. A chest opened by a player spits out 5+ pickups at
// one spot within a fraction of a second; floor loot appears all at once at the very start (before 40 s) and is ignored.
class Spy : ReplayReader
{
    const double MinTime = 40, Window = 0.6, Radius = 250; const int MinItems = 5;
    readonly List<(double t, double x, double y)> pk = new();
    double now;
    readonly List<double> offsets = new();
    /// <summary>game clock minus replay time (seconds): turns a game-clock time into the time bursts are stamped with</summary>
    public double ClockOffset => offsets.Count == 0 ? 0 : offsets.OrderBy(x => x).ElementAt(offsets.Count / 2);
    readonly Dictionary<uint, (double x, double y)> pawnPos = new();
    /// <summary>container name -> where it was first searched (the searching player's position), game seconds</summary>
    public readonly Dictionary<string, (double x, double y, double t)> Opened = new();
    protected override void OnExportRead(uint channelIndex, Unreal.Core.Contracts.INetFieldExportGroup? exportGroup)
    {
        var actor = Channels[channelIndex]?.Actor;
        if (exportGroup is FortniteReplayReader.Models.NetFieldExports.PlayerPawn pp)
        {
            if (pp.ReplayLastTransformUpdateTimeStamp is float w && w > 100 && offsets.Count < 2000) offsets.Add(w - now);
            if (actor != null && pp.ReplicatedMovement.HasValue) pawnPos[actor.ActorNetGUID.Value] = (pp.ReplicatedMovement.Value.Location.X, pp.ReplicatedMovement.Value.Location.Y);
        }
        else if (exportGroup is ContainerExport cx && actor != null && cx.SearchingPawn is uint sp && sp != 0 && pawnPos.TryGetValue(sp, out var pos)
            && _netGuidCache.TryGetPathName(actor.ActorNetGUID.Value, out var name) && !Opened.ContainsKey(name))
            Opened[name] = (pos.x, pos.y, now);
        base.OnExportRead(channelIndex, exportGroup);
    }
    public Spy() : base(null, ParseMode.Full) { }
    public override void ReadDemoFrameIntoPlaybackPackets(FArchive archive)
    {
        var start = archive.Position;
        if (archive.NetworkVersion >= NetworkVersionHistory.HISTORY_MULTIPLE_LEVELS) archive.ReadInt32();
        now = archive.ReadSingle();
        archive.Seek(start, SeekOrigin.Begin);
        base.ReadDemoFrameIntoPlaybackPackets(archive);
    }
    public override void ProcessBunch(DataBunch bunch)
    {
        bool had = Channels[bunch.ChIndex]?.Actor != null;
        base.ProcessBunch(bunch);
        var a = Channels[bunch.ChIndex]?.Actor;
        if (!had && a != null && a.ActorNetGUID.IsDynamic() && now >= MinTime && a.Archetype != null
            && _netGuidCache.TryGetPathName(a.Archetype.Value, out var path) && path.Contains("FortPickupAthena"))
            pk.Add((now, a.Location.X, a.Location.Y));
    }
    public List<(double x, double y, int n, double t)> Bursts()
    {
        var res = new List<(double, double, int, double)>();
        var used = new bool[pk.Count];
        for (int i = 0; i < pk.Count; i++)
        {
            if (used[i]) continue;
            used[i] = true; var grp = new List<int> { i };
            for (int j = i + 1; j < pk.Count && pk[j].t - pk[i].t <= Window; j++)
                if (!used[j] && Math.Sqrt(Math.Pow(pk[j].x - pk[i].x, 2) + Math.Pow(pk[j].y - pk[i].y, 2)) <= Radius) { used[j] = true; grp.Add(j); }
            if (grp.Count >= MinItems) res.Add((grp.Average(k => pk[k].x), grp.Average(k => pk[k].y), grp.Count, grp.Average(k => pk[k].t)));
        }
        return res;
    }
}
