// Containers (chests, ammo boxes, ...) are placed in the map, so a replay never says where they are. But every one of them has a stable
// unique name (Tiered_Chest_Sunflower_C_UAID_...), and when a player searches it the replay says WHICH pawn is searching (SearchingPawn):
// that player stands next to the container, so the player's position at that moment is the container's position. Over many matches the
// same name gives the same spot within about a metre. The parser finds these classes because this assembly's name contains "ReplayReader".
using Unreal.Core.Attributes;
using Unreal.Core.Contracts;
using Unreal.Core.Models.Enums;

public abstract class ContainerExport : INetFieldExportGroup
{
    [NetFieldExport("bAlreadySearched", RepLayoutCmdType.PropertyBool)]
    public bool? bAlreadySearched { get; set; }
    [NetFieldExport("SearchingPawn", RepLayoutCmdType.PropertyObject)]
    public uint? SearchingPawn { get; set; }
}

[NetFieldExportGroup("/Game/Building/ActorBlueprints/Containers/Tiered_Chest_Athena.Tiered_Chest_Athena_C")] public class CxChestAthena : ContainerExport { }
[NetFieldExportGroup("/Game/Building/ActorBlueprints/Containers/Tiered_Chest_Sunflower.Tiered_Chest_Sunflower_C")] public class CxChestSunflower : ContainerExport { }
[NetFieldExportGroup("/Game/Building/ActorBlueprints/Containers/Tiered_Chest_Apollo_IceBox.Tiered_Chest_Apollo_IceBox_C")] public class CxChestIceBox : ContainerExport { }
[NetFieldExportGroup("/Game/Building/ActorBlueprints/Containers/AlwaysSpawn_RareChest.AlwaysSpawn_RareChest_C")] public class CxRareChest : ContainerExport { }
[NetFieldExportGroup("/Game/Building/ActorBlueprints/Containers/AlwaysSpawn_NormalChest.AlwaysSpawn_NormalChest_C")] public class CxNormalChest : ContainerExport { }
[NetFieldExportGroup("/Game/Building/ActorBlueprints/Containers/Tiered_Ammo_Athena.Tiered_Ammo_Athena_C")] public class CxAmmo : ContainerExport { }
[NetFieldExportGroup("/Game/Building/ActorBlueprints/Containers/FoodBox_Produce_Athena.FoodBox_Produce_Athena_C")] public class CxProduce : ContainerExport { }
[NetFieldExportGroup("/Game/Building/ActorBlueprints/Containers/Barrel_FishingRod_Container_Athena.Barrel_FishingRod_Container_Athena_C")] public class CxFishingBarrel : ContainerExport { }
[NetFieldExportGroup("/Game/Environments/Helios/Props/Gameplay/Gameplay_CashRegister_A/Blueprints/BP_BGA_Gameplay_CashRegister_A.BP_BGA_Gameplay_CashRegister_A_C")] public class CxCashRegister : ContainerExport { }
