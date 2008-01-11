function [background_image,data] = read_trx( filename )
% READ_TRX(filename)
% 
% function to convert data from .trx format (from flytrax) into a
% Matlab-friendly format 

% opens file in "read only" mode
fp = fopen( filename, 'r' ) ;

% read header ==================
version = double( fread( fp, 1, 'int32' ) );  % fread reads file (file identifier, size, string percision)
if version == 1,
   nnums = 6;
elseif version == 2,
   nnums = 7;
else,
   error( 'version not supported -- TRX versions 1 and 2 only' ); % this error means fopen can't open file given size and percision settings
end

% read backgound image =========
im_height = double( fread( fp, 1, 'int32' ) );   % 32-bit integer
im_width = double( fread( fp, 1, 'int32' ) );

im_nbytes = im_height*im_width;  % image size

background_image = fread(fp,[im_width,im_height],'uint8'); % unsigned 8-bit integer

% read data ====================
data = fread(fp,[nnums,inf],'float64');  % data position X, position Y, orientation (slope), window X, windowY, time, (area - v2 only)

% close file ====================
fclose(fp);