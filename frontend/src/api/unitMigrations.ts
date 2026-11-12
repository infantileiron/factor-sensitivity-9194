import {request} from './client';

export interface FactorConversion{
 factor_id:string;
 scale:number;
 offset:number;
 new_unit:string;
}
export interface MigrationBody{
 source_model_id:string;
 source_space_id:string;
 new_model_name:string;
 new_space_name:string;
 description:string;
 conversions:FactorConversion[];
}
export const previewMigration=(body:MigrationBody)=>request('/unit-migrations/preview','POST',body);
export const createMigration=(body:MigrationBody)=>request('/unit-migrations','POST',body);
