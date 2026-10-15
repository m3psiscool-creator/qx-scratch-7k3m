// Reads tournament replays and prints where every player landed.
//   landings <file.replay> [more files...]      -> one JSON object per line
// Landing = the first moment after leaving the battle bus that the player is on the ground (vertical speed exactly 0).
using System.Globalization;
using System.Text;
using FortniteReplayReader;
using Unreal.Core.Models.Enums;

var reader = new ReplayReader(null, ParseMode.Full);
var inv = CultureInfo.InvariantCulture;

foreach (var file in args)
{
    var sb = new StringBuilder();
    try
    {
        var replay = reader.ReadReplay(file);
        var g = replay.GameData;
        sb.Append("{\"file\":").Append(Q(Path.GetFileName(file)))
          .Append(",\"playlist\":").Append(Q(g.CurrentPlaylist))
          .Append(",\"players\":[");
        bool first = true;
        var trail = new List<(double x, double y)>();
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
