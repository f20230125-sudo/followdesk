// Secrets travel through private process stdin, never arguments or logs.
import {createCipheriv,createDecipheriv,randomBytes} from 'node:crypto';
try {
  let raw='';
  for await(const chunk of process.stdin){raw+=chunk;if(raw.length>32768)throw Error();}
  const input=JSON.parse(raw);
  if(!/^[a-f0-9]{64}$/.test(input.key)||typeof input.value!=='string')throw Error();
  const key=Buffer.from(input.key,'hex');
  const aad=Buffer.from('followdesk/local-vault/v1');
  if(process.argv[2]==='seal'){
    const nonce=randomBytes(12);
    const cipher=createCipheriv('aes-256-gcm',key,nonce);
    cipher.setAAD(aad);
    const ciphertext=Buffer.concat([cipher.update(input.value,'utf8'),cipher.final()]);
    process.stdout.write(Buffer.concat([nonce,cipher.getAuthTag(),ciphertext]).toString('base64'));
  }else if(process.argv[2]==='open'){
    const blob=Buffer.from(input.value,'base64');
    if(blob.length<29)throw Error();
    const decipher=createDecipheriv('aes-256-gcm',key,blob.subarray(0,12));
    decipher.setAAD(aad);decipher.setAuthTag(blob.subarray(12,28));
    process.stdout.write(Buffer.concat([decipher.update(blob.subarray(28)),decipher.final()]).toString('utf8'));
  }else throw Error();
}catch{process.stderr.write('Encrypted storage operation failed.');process.exitCode=1;}
