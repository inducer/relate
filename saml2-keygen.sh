#! /bin/sh

# nicked and customized from Shibboleth
# Run as
# ./saml2-keygen.sh –h your.host.name –e https://your.host.name/saml2/metadata -y 10

while getopts h:u:g:o:e:y:bf c
     do
         case $c in
           u)         USER=$OPTARG;;
           g)         GROUP=$OPTARG;;
           o)         OUT=$OPTARG;;
           b)         BATCH=1;;
           f)         FORCE=1;;
           h)         FQDN=$OPTARG;;
           e)         ENTITYID=$OPTARG;;
           y)         YEARS=$OPTARG;;
           \?)        echo "keygen [-o output directory (default .)] [-u username to own keypair] [-g owning groupname] [-h hostname for cert] [-y years to issue cert] [-e entityID to embed in cert]"
                      exit 1;;
         esac
     done
if [ -z "$OUT" ] ; then
    OUT=saml-config
    mkdir -p saml-config
fi

if [ -n "$FORCE" ] ; then
    rm $OUT/sp-key.pem $OUT/sp-cert.pem
fi

if  [ -s $OUT/sp-key.pem -o -s $OUT/sp-cert.pem ] ; then
    if [ -z "$BATCH" ] ; then
        echo The files $OUT/sp-key.pem and/or $OUT/sp-cert.pem already exist!
        echo Use -f option to force recreation of keypair.
        exit 2
    fi
    exit 0
fi

if [ -z "$FQDN" ] ; then
    FQDN=`hostname`
fi

if [ -z "$YEARS" ] ; then
    YEARS=10
fi

DAYS=`expr $YEARS \* 365`

if [ -z "$ENTITYID" ] ; then
    ALTNAME=DNS:$FQDN
else
    ALTNAME=DNS:$FQDN,URI:$ENTITYID
fi

SSLCNF=$OUT/sp-cert.cnf
cat >$SSLCNF <<EOF
# OpenSSL configuration file for creating sp-cert.pem
[req]
prompt=no
default_bits=2048
encrypt_key=no
default_md=sha1
distinguished_name=dn
# PrintableStrings only
string_mask=MASK:0002
x509_extensions=ext
[dn]
CN=$FQDN
[ext]
subjectAltName=$ALTNAME
subjectKeyIdentifier=hash
EOF

touch $OUT/sp-key.pem
chmod 600 $OUT/sp-key.pem
if [ -z "$BATCH" ] ; then
    openssl req -config $SSLCNF -new -x509 -days $DAYS -keyout $OUT/sp-key.pem -out $OUT/sp-cert.pem
else
    openssl req -config $SSLCNF -new -x509 -days $DAYS -keyout $OUT/sp-key.pem -out $OUT/sp-cert.pem 2> /dev/null
fi
rm $SSLCNF

if  [ -s $OUT/sp-key.pem -a -n "$USER" ] ; then
    chown $USER $OUT/sp-key.pem $OUT/sp-cert.pem
fi

if  [ -s $OUT/sp-key.pem -a -n "$GROUP" ] ; then
    chgrp $GROUP $OUT/sp-key.pem $OUT/sp-cert.pem
fi
