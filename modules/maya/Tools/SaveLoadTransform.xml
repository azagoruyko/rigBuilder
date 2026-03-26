<module name="saveLoadTransform" muted="0" uid="8fb4d6c44f1f4743a962a6385fadb21c">
<run><![CDATA[import pymel.core as pm
import json

if @mode==0: # save transformation
    data = {}    
    for n in @objects:
        data[n] = pm.xform(n, q=True, ws=True, m=True)

    with open(@file, "w") as f:
        json.dump(data, f)
        
    print("Transforms saved")

else: # load transformation
    with open(@file, "r") as f:
        data = json.load(f)
        
    data = {k:v for k,v in data.items() if pm.objExists(k) and (@loadEverything or k in @objects)}
    
    for n in sorted(data, key=lambda n:len(pm.PyNode(n).getAllParents())):
        pm.xform(n, ws=True, m=data[n])
            
    print("Transforms restored")]]></run>
<attributes>
<attr name="mode" template="radioButton" category="General" connect=""><![CDATA[{"items": ["Save", "Load"], "current": 0, "columns": 3, "default": "current"}]]></attr>
<attr name="objects" template="listBox" category="General" connect=""><![CDATA[{"items": ["Spine2", "Neck", "Left_Armpit", "Left_ShoulderFan", "Right_Armpit", "Left_Shoulder", "Left_Arm", "Right_Shoulder", "Right_Arm", "Chin_JNT", "ForeHead_JNT", "Face_JNT", "Jaw_JNT", "L_Corner_Lip_JNT", "L_EyeSocket_01_JNT", "L_EyeSocket_02_JNT", "L_EyeSocket_03_JNT", "L_ForeHead_01_JNT", "L_ForeHead_02_JNT", "L_ForeHead_03_JNT", "Mid_Brow_JNT", "L_Inner_Brow_JNT", "L_Inner_Lower_Mid_Lid_JNT", "L_Inner_Upper_Mid_Lid_JNT", "L_LowerNasolabial_01_JNT", "L_Lower_Cheek_JNT", "L_Lower_Mid_Lid_JNT", "L_Mid_Brow_JNT", "L_Nasolabial_Lip_JNT", "L_Nostril_JNT", "L_Outer_Brow_JNT", "L_Outer_Lower_Mid_Lid_JNT", "L_Outer_Upper_Mid_Lid_JNT", "L_Sneer_JNT", "L_UpperNasolabial_01_JNT", "L_UpperNasolabial_02_JNT", "L_Upper_Cheek_02_JNT", "L_Upper_Cheek_JNT", "L_Upper_Mid_Lid_JNT", "LowerNasolabial_JNT", "Nose_JNT", "R_Corner_Lip_JNT", "R_EyeSocket_01_JNT", "R_EyeSocket_02_JNT", "R_EyeSocket_03_JNT", "R_ForeHead_01_JNT", "R_ForeHead_02_JNT", "R_ForeHead_03_JNT", "R_Inner_Brow_JNT", "R_Inner_Lower_Mid_Lid_JNT", "R_Inner_Upper_Mid_Lid_JNT", "R_Lower_Cheek_JNT", "R_Lower_Mid_Lid_JNT", "R_Mid_Brow_JNT", "R_Nasolabial_Lip_JNT", "R_Nostril_JNT", "R_Outer_Brow_JNT", "R_Outer_Lower_Mid_Lid_JNT", "R_Outer_Upper_Mid_Lid_JNT", "R_LowerNasolabial_01_JNT", "R_Sneer_JNT", "R_UpperNasolabial_01_JNT", "R_UpperNasolabial_02_JNT", "R_Upper_Cheek_02_JNT", "R_Upper_Cheek_JNT", "R_Upper_Mid_Lid_JNT", "noseTip_JNT", "L_Corrugator_JNT", "R_Corrugator_JNT", "L_Lower_Inner_Orb_JNT", "L_Lower_Mid_Orb_JNT", "L_Lower_Outer_Orb_JNT", "R_Lower_Inner_Orb_JNT", "R_Lower_Mid_Orb_JNT", "R_Lower_Outer_Orb_JNT", "L_Outer_Malar_JNT", "R_Outer_Malar_JNT", "Chin_Under_JNT", "R_Chin_Under_JNT", "L_Chin_Under_JNT", "L_Levator_Labii_Inner_JNT", "Mid_Levator_Labii_JNT", "R_Levator_Labii_Inner_JNT", "R_Nasolabial_Crease_03_JNT", "L_Temporal_JNT", "R_Temporal_JNT", "L_Nasolabial_Crease_03_JNT", "Throat_JNT", "L_Levator_Labii_Outer_JNT", "R_Levator_Labii_Outer_JNT", "Upper_Mid_Lip_Thickness_01_JNT", "L_Nasolabial_Crease_01_JNT", "L_Nasolabial_Crease_02_JNT", "R_Nasolabial_Crease_01_JNT", "R_Nasolabial_Crease_02_JNT", "L_Chin_JNT", "R_Chin_JNT", "L_Lower_Mid_Lip_03_low_JNT", "L_Lower_Mid_Lip_02_low_JNT", "L_Lower_Mid_Lip_01_low_JNT", "Lower_Mid_Lip_Thickness_01_low_JNT", "R_Lower_Mid_Lip_01_low_JNT", "R_Lower_Mid_Lip_02_low_JNT", "R_Lower_Mid_Lip_03_low_JNT", "R_Lower_Mid_Lip_03_up_JNT", "R_Lower_Mid_Lip_02_up_JNT", "R_Lower_Mid_Lip_01_up_JNT", "Lower_Mid_Lip_Thickness_01_JNT", "L_Lower_Mid_Lip_01_up_JNT", "L_Lower_Mid_Lip_02_up_JNT", "L_Lower_Mid_Lip_03_up_JNT", "L_Upper_Mid_Lip_03_low_JNT", "L_Upper_Mid_Lip_03_up_JNT", "L_Upper_Mid_Lip_02_low_JNT", "L_Upper_Mid_Lip_02_up_JNT", "L_Upper_Mid_Lip_01_low_JNT", "L_Upper_Mid_Lip_01_up_JNT", "Upper_Mid_Lip_Thickness_up_JNT", "R_Upper_Mid_Lip_01_low_JNT", "R_Upper_Mid_Lip_01_up_JNT", "R_Upper_Mid_Lip_02_low_JNT", "R_Upper_Mid_Lip_02_up_JNT", "R_Upper_Mid_Lip_03_low_JNT", "R_Upper_Mid_Lip_03_up_JNT", "L_Nasolabial_Crease_04_JNT", "L_LowerNasolabial_02_JNT", "R_Nasolabial_Crease_04_JNT", "R_LowerNasolabial_02_JNT", "L_UpperNasolabial_03_JNT", "R_UpperNasolabial_03_JNT", "R_jawSide_02_JNT", "R_jawSide_JNT", "R_Chin_02_JNT", "R_Upper_Cheek_03_JNT", "L_Upper_Cheek_03_JNT", "L_Chin_02_JNT", "L_jawSide_JNT", "L_jawSide_02_JNT", "cust_nose_bridge_JNT", "cust_nose_bridge_02_JNT", "cust_L_Eyelid_JNT", "cust_R_Eyelid_JNT", "cust_Throat_02_JNT", "cust_noseLow_JNT", "cust_L_jawBone_JNT", "cust_R_jawBone_JNT", "cust_R_Chin_Under_02_JNT", "cust_L_Chin_Under_02_JNT"], "default": "items"}]]></attr>
<attr name="file" template="lineEdit" category="General" connect=""><![CDATA[{"value": "o:/temp/data.txt", "default": "value", "min": "", "max": "", "validator": 0}]]></attr>
<attr name="loadEverything" template="checkBox" category="General" connect=""><![CDATA[{"checked": true, "default": "checked"}]]></attr>
</attributes>
<children>
</children>
</module>