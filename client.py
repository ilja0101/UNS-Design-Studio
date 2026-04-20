# client.py
# UNS Design Studio — CLI control client
#
# Author : Ilja Bartels  |  https://github.com/Ilja0101
# License: MIT  |  https://github.com/Ilja0101/UNS-Design-Studio
#
# Interactive command-line client for direct OPC-UA access and plant control.

import time
import socket
import json
import inquirer
from opcua import Client
from recipe import Recipe, recipe_data

SERVER_ENDPOINT = "opc.tcp://10.10.3.4:4840/freeopcua/server/"
NAMESPACE_URI   = "http://VirtualUNS.com/uns"
TCP_SERVER_IP   = "0.0.0.0"
TCP_SERVER_PORT = 9999

ENTERPRISE_STRUCTURE = {
    "CrispCraft": ["FactoryAntwerp",    "FactoryGhent"],
    "FlakeMill":   ["FactoryLeiden",    "FactoryGroningen"],
    "FrostLine":     ["FactoryDortmund",   "FactoryBremen",   "FactoryHanover",
                      "FactoryLeipzig",   "FactoryCologne",   "FactoryDresden"],
    "RootCore":  ["FactoryLille"],
    "SugarWorks": ["FactoryBruges",  "FactoryLiege"],
}


def send_anomaly_data(anomaly_overrides=None, anomaly_states=None):
    if anomaly_overrides is None and anomaly_states is None:
        return
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((TCP_SERVER_IP, TCP_SERVER_PORT))
            data = {}
            if anomaly_overrides:
                data['anomaly_overrides'] = anomaly_overrides
            if anomaly_states:
                data['anomaly_states'] = anomaly_states
            s.send(json.dumps(data).encode('utf-8'))
    except Exception as e:
        print(f"Verzenden anomalie-data mislukt: {e}")


def get_available_recipes(group):
    return [r.value for r in Recipe if recipe_data.get(r, {}).get('group') == group]


def get_default_recipe(group):
    available = get_available_recipes(group)
    return available[0] if available else "--NA--"


def get_equipment_options(group, plant):
    """Geeft beschikbare procesapparatuur terug per divisie/fabriek."""
    options = {}
    if group == "CrispCraft":
        options["Snijmachinesnelheid"]   = "cutter_speed"
        options["Blancheertemperatuur"]  = "blancher_temperature"
        options["Frituurtemperatuur"]    = "fryer_temperature"
        options["Koelingtunneltemp."]    = "freezer_temperature"
    elif group == "FlakeMill":
        options["Trommelsnelheid"]       = "drum_speed"
        options["Trommeltemperatuur"]    = "drum_temperature"
    elif group == "FrostLine":
        options["Snijmachinesnelheid"]   = "cutter_speed"
        options["Blancheertemperatuur"]  = "blancher_temperature"
        options["Voorfrituurtemperatuur"]= "fryer_temperature"
        options["IQF-tunneltemperatuur"] = "freezer_temperature"
    elif group == "RootCore":
        options["Extractietemperatuur"]  = "extraction_temperature"
    elif group == "SugarWorks":
        options["Diffusietemperatuur"]   = "diffusion_temperature"
        options["Verdampertemperatuur"]  = "evaporator_temperature"
        options["Kristallisatortemp."]   = "crystallizer_temperature"
    return options


def start_all_plants(client, idx, enterprise_obj):
    print("\n🚀 Alle fabrieken opstarten (ProcessState=True + standaard recept per divisie)...\n")
    started_count = 0
    for group_name, plants in ENTERPRISE_STRUCTURE.items():
        default_recipe = get_default_recipe(group_name)
        print(f"  [{group_name}] standaard recept: {default_recipe}")
        site_obj = enterprise_obj.get_child([f"{idx}:{group_name}"])
        for plant_name in plants:
            try:
                area_obj            = site_obj.get_child([f"{idx}:{plant_name}"])
                line_obj            = area_obj.get_child([f"{idx}:ProductionLine"])
                process_control_obj = line_obj.get_child([f"{idx}:ProcessControl"])
                process_state       = process_control_obj.get_child([f"{idx}:ProcessState"])
                recipe_node         = process_control_obj.get_child([f"{idx}:Recipe"])
                process_state.set_value(True)
                recipe_node.set_value(default_recipe)
                short = plant_name.replace("Factory", "")
                print(f"    ✓ {short} gestart met recept '{default_recipe}'")
                started_count += 1
            except Exception as e:
                print(f"    ✗ {plant_name} mislukt: {e}")
    print(f"\n✅ {started_count} fabrieken succesvol opgestart.\n")


def stop_all_plants(client, idx, enterprise_obj):
    print("\n🛑 Alle fabrieken stoppen (ProcessState=False + Recept='--NA--')...\n")
    stopped_count = 0
    for group_name, plants in ENTERPRISE_STRUCTURE.items():
        site_obj = enterprise_obj.get_child([f"{idx}:{group_name}"])
        for plant_name in plants:
            try:
                area_obj            = site_obj.get_child([f"{idx}:{plant_name}"])
                line_obj            = area_obj.get_child([f"{idx}:ProductionLine"])
                process_control_obj = line_obj.get_child([f"{idx}:ProcessControl"])
                process_state       = process_control_obj.get_child([f"{idx}:ProcessState"])
                recipe_node         = process_control_obj.get_child([f"{idx}:Recipe"])
                process_state.set_value(False)
                recipe_node.set_value("--NA--")
                short = plant_name.replace("Factory", "")
                print(f"    ✓ {short} gestopt")
                stopped_count += 1
            except Exception as e:
                print(f"    ✗ {plant_name} mislukt: {e}")
    print(f"\n✅ {stopped_count} fabrieken succesvol gestopt.\n")


def individual_plant_control(client, idx, enterprise_obj):
    group_choices = list(ENTERPRISE_STRUCTURE.keys()) + ['← Terug naar hoofdmenu']
    group_q = [inquirer.List('group', message="Selecteer divisie", choices=group_choices)]
    group_ans = inquirer.prompt(group_q)
    if group_ans['group'] == '← Terug naar hoofdmenu':
        return False
    selected_group = group_ans['group']

    plant_display  = [p.replace("Factory", "") for p in ENTERPRISE_STRUCTURE[selected_group]]
    plant_choices  = plant_display + ['← Terug', '← Terug naar hoofdmenu']
    plant_q = [inquirer.List('plant', message=f"[{selected_group}] Selecteer fabriek", choices=plant_choices)]
    plant_ans = inquirer.prompt(plant_q)
    if plant_ans['plant'] == '← Terug naar hoofdmenu':
        return False
    if plant_ans['plant'] == '← Terug':
        return individual_plant_control(client, idx, enterprise_obj)

    selected_plant_short = plant_ans['plant']
    selected_plant       = f"Factory{selected_plant_short}"

    site_obj            = enterprise_obj.get_child([f"{idx}:{selected_group}"])
    area_obj            = site_obj.get_child([f"{idx}:{selected_plant}"])
    line_obj            = area_obj.get_child([f"{idx}:ProductionLine"])
    process_control_obj = line_obj.get_child([f"{idx}:ProcessControl"])
    process_state       = process_control_obj.get_child([f"{idx}:ProcessState"])
    recipe_node         = process_control_obj.get_child([f"{idx}:Recipe"])
    prefix              = f"{selected_group}{selected_plant}"

    while True:
        questions = [
            inquirer.List('action',
                          message=f"[{selected_group} – {selected_plant_short}] Kies actie",
                          choices=[
                              'ProcessState instellen',
                              'Recept instellen',
                              'Continue anomalie activeren',
                              '← Terug naar fabriekselectie',
                              '← Terug naar hoofdmenu',
                          ]),
        ]
        answers = inquirer.prompt(questions)

        if answers['action'] == '← Terug naar hoofdmenu':
            return False
        elif answers['action'] == '← Terug naar fabriekselectie':
            return individual_plant_control(client, idx, enterprise_obj)

        elif answers['action'] == 'ProcessState instellen':
            state_q = [inquirer.List('state',
                                     message="Processtatus instellen",
                                     choices=['True  – In bedrijf ▶', 'False – Gestopt ■'])]
            state_ans = inquirer.prompt(state_q)
            value = state_ans['state'].startswith('True')
            process_state.set_value(value)
            status = "▶ In bedrijf" if value else "■ Gestopt"
            print(f"  ProcessState → {status}")

        elif answers['action'] == 'Recept instellen':
            available     = get_available_recipes(selected_group)
            recipe_choices = available + ['[Aangepast invoeren]', '--NA--']
            recipe_q = [inquirer.List('rec', message="Selecteer recept", choices=recipe_choices)]
            rec_ans   = inquirer.prompt(recipe_q)
            recipe_value = rec_ans['rec']
            if recipe_value == '[Aangepast invoeren]':
                custom_q   = [inquirer.Text('custom', message="Voer receptnaam in")]
                custom_ans = inquirer.prompt(custom_q)
                recipe_value = custom_ans['custom']
            recipe_node.set_value(recipe_value)
            print(f"  Recept → '{recipe_value}'")

        elif answers['action'] == 'Continue anomalie activeren':
            equip_options = get_equipment_options(selected_group, selected_plant)
            cat_choices   = ['Infeedsilo-niveaus', 'Uitgaand gewicht']
            if equip_options:
                cat_choices.append('Procesapparatuur')
            cat_choices += ['Pompen', 'Regelkleppen', 'Ventilatoren', 'Tussentijdse tanks']

            cat_q   = [inquirer.List('cat', message="Selecteer anomaliecategorie", choices=cat_choices)]
            cat_ans = inquirer.prompt(cat_q)
            category  = cat_ans['cat']
            overrides = {}

            if category == 'Infeedsilo-niveaus':
                silos_q = inquirer.Checkbox('silos', message="Selecteer silo's",
                                            choices=[f"Silo{i}" for i in range(1, 5)])
                sel = inquirer.prompt([silos_q])['silos']
                for s in sel:
                    num   = int(s[-1])
                    val_q = inquirer.Text('val', message=f"Anomaliewaarde voor Silo {num} (tons)")
                    val   = float(inquirer.prompt([val_q])['val'])
                    overrides[f"{prefix}InfeedSilo{num}Level"] = val

            elif category == 'Uitgaand gewicht':
                val_q = inquirer.Text('val', message="Anomalie uitgaand gewicht (tons)")
                val   = float(inquirer.prompt([val_q])['val'])
                overrides[f"{prefix}OutboundWeight"] = val

            elif category == 'Procesapparatuur':
                equip_q = inquirer.Checkbox('equip', message="Selecteer apparatuur",
                                            choices=list(equip_options.keys()))
                sel = inquirer.prompt([equip_q])['equip']
                for display in sel:
                    suffix = equip_options[display].capitalize()
                    val_q  = inquirer.Text('val', message=f"Anomaliewaarde voor {display}")
                    val    = float(inquirer.prompt([val_q])['val'])
                    overrides[f"{prefix}{suffix}"] = val

            elif category in ['Pompen', 'Regelkleppen', 'Ventilatoren', 'Tussentijdse tanks']:
                util_map = {
                    'Pompen':             ('Pump',  12, ['Speed','Current','Vibration','BearingTemp','Flow','SuctionPressure','DischargePressure']),
                    'Regelkleppen':       ('Valve', 20, ['Position','Current','Torque']),
                    'Ventilatoren':       ('Fan',   10, ['Speed','Current','Vibration','BearingTemp','Damper','Airflow']),
                    'Tussentijdse tanks': ('Tank',  10, ['Level','Temp','Pressure','pH','Conductivity','AgitCurrent']),
                }
                short, num_inst, params = util_map[category]
                inst_choices = [f"{short}{i:02d}" for i in range(1, num_inst + 1)]
                inst_q       = inquirer.Checkbox('insts',
                                                 message=f"Selecteer {category.lower()} instanties",
                                                 choices=inst_choices)
                sel_insts = inquirer.prompt([inst_q])['insts']
                if not sel_insts:
                    print("  Geen instanties geselecteerd.")
                    continue
                param_q   = [inquirer.List('param', message="Selecteer parameter", choices=params)]
                sel_param = inquirer.prompt(param_q)['param']
                val_q     = [inquirer.Text('val', message=f"Anomaliewaarde voor {sel_param} (zelfde voor alle)")]
                val       = float(inquirer.prompt(val_q)['val'])
                for inst in sel_insts:
                    overrides[f"{prefix}{inst}{sel_param}"] = val

            dur_q    = inquirer.Text('dur', message="Duur in seconden (0 = permanent)", default="30")
            duration = float(inquirer.prompt([dur_q])['dur'])
            send_anomaly_data(anomaly_overrides=overrides)
            print(f"  ⚠️  Anomalie geactiveerd op {len(overrides)} tag(s)")
            if duration > 0:
                time.sleep(duration)
                reset = {k: None for k in overrides}
                send_anomaly_data(anomaly_overrides=reset)
                print("  ✅ Anomalie gewist")
    return True


def print_banner():
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        GlobalFoodCo – Simulatorbesturing         ║")
    print("║   CrispCraft · FlakeMill · FrostLine                   ║")
    print("║   RootCore · De BietenBende                              ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


def main():
    print_banner()
    client = Client(SERVER_ENDPOINT)
    try:
        client.connect()
        print(f"✅ Verbonden met GlobalFoodCo OPC UA server ({SERVER_ENDPOINT})\n")
        root           = client.get_root_node()
        idx            = client.get_namespace_index(NAMESPACE_URI)
        enterprise_obj = root.get_child(["0:Objects", f"{idx}:GlobalFoodCo"])

        while True:
            main_choices = [
                '🚀  Alle fabrieken opstarten  (ProcessState=True + standaard recept)',
                '🛑  Alle fabrieken stoppen    (ProcessState=False + Recept="--NA--")',
                '🏭  Individuele fabrieksbesturing',
                '🚪  Afsluiten',
            ]
            main_q   = [inquirer.List('main_action', message="Hoofdmenu", choices=main_choices)]
            main_ans = inquirer.prompt(main_q)
            action   = main_ans['main_action']

            if action.startswith('🚪'):
                break
            elif action.startswith('🚀'):
                start_all_plants(client, idx, enterprise_obj)
            elif action.startswith('🛑'):
                stop_all_plants(client, idx, enterprise_obj)
            elif action.startswith('🏭'):
                continue_loop = individual_plant_control(client, idx, enterprise_obj)
                if not continue_loop:
                    print("\nTerug naar hoofdmenu...\n")

    finally:
        client.disconnect()
        print("\n👋 Verbinding verbroken. Tot ziens van GlobalFoodCo!")


if __name__ == "__main__":
    main()
