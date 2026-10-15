using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using System.Text.Json;

var dir = args[0]; var keys = args[1]; var usmap = args[2]; var pattern = args[3];
var provider = new DefaultFileProvider(dir, SearchOption.TopDirectoryOnly, new VersionContainer(EGame.GAME_UE5_LATEST));
provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmap);
provider.Initialize();
var j = JsonDocument.Parse(File.ReadAllText(keys)).RootElement.GetProperty("data");
provider.SubmitKey(new FGuid(), new FAesKey(j.GetProperty("mainKey").GetString()));
int n = 0;
foreach (var d in j.GetProperty("dynamicKeys").EnumerateArray())
{
    try { n += provider.SubmitKey(new FGuid(d.GetProperty("pakGuid").GetString()), new FAesKey(d.GetProperty("key").GetString())); } catch {}
}
Console.WriteLine("mounted dynamic: " + n + ", files: " + provider.Files.Count);
var rx = new System.Text.RegularExpressions.Regex(pattern, System.Text.RegularExpressions.RegexOptions.IgnoreCase);
int c = 0;
foreach (var f in provider.Files.Keys) if (rx.IsMatch(f)) { Console.WriteLine(f); if (++c > 400) break; }
if (args.Length > 4 && args[4].StartsWith("json:"))
{
    Console.WriteLine(Newtonsoft.Json.JsonConvert.SerializeObject(provider.LoadPackage(args[4].Substring(5)).GetExports(), Newtonsoft.Json.Formatting.Indented));
}
else if (args.Length > 4)
{
    foreach (var spec in args[4].Split(','))
    {
        var o = provider.LoadPackageObject<CUE4Parse.UE4.Assets.Exports.Texture.UTexture2D>(spec + "." + spec.Substring(spec.LastIndexOf('/') + 1));
        var bmp = CUE4Parse_Conversion.Textures.TextureDecoder.Decode(o, CUE4Parse.UE4.Assets.Exports.Texture.ETexturePlatform.DesktopMobile);
        var bytes = CUE4Parse_Conversion.Textures.TextureEncoder.Encode(bmp, CUE4Parse_Conversion.Options.ETextureFormat.Png, false, out var ext, 100);
        var name = Path.Combine(args[5], spec.Substring(spec.LastIndexOf('/') + 1) + ".png");
        File.WriteAllBytes(name, bytes);
        Console.WriteLine(name + " " + bmp.Width + "x" + bmp.Height);
    }
}
