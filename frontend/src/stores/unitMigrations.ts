import {ref} from 'vue';
import {previewMigration,createMigration,type MigrationBody} from '../api/unitMigrations';

export interface FactorLedger{
 factor_id:string;name:string;old_unit:string;new_unit:string;
 scale:number;offset:number;changed:boolean;
 old_linear:number;new_linear:number;
 old_quadratic:number;new_quadratic:number;
 old_low:number;new_low:number;old_high:number;new_high:number;
}
export interface MigrationPreview{
 source_model:any;source_space:any;derived_model:any;derived_ranges:any[];
 name_conflict:boolean;
 comparison:{formula:string;intercept:{old:number;new:number};
  factors:FactorLedger[];interactions:{left:string;right:string;old_coefficient:number;new_coefficient:number}[]};
}
export function useMigration(){
 const preview=ref<MigrationPreview|null>(null);
 const busy=ref(false);
 const error=ref('');
 async function runPreview(body:MigrationBody){
  busy.value=true;error.value='';
  try{preview.value=await previewMigration(body)}
  catch(e){preview.value=null;error.value=(e as Error).message}
  finally{busy.value=false}
 }
 async function confirm(body:MigrationBody){
  busy.value=true;error.value='';
  try{const r=await createMigration(body);preview.value=null;return r}
  catch(e){error.value=(e as Error).message;throw e}
  finally{busy.value=false}
 }
 function reset(){preview.value=null;error.value=''}
 return {preview,busy,error,runPreview,confirm,reset};
}
