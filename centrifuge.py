import re
import tornado.ioloop
import tornado.web
import tornado.httpclient
import Image
import numpy
import numpy as np
from numpy import fromstring, ubyte, e, array, add, uint8, copy, clip
from scipy.ndimage.filters import convolve1d
from cStringIO import StringIO

def classify_val(val):
    v = val
    try:
        return int(val)
    except ValueError:
        try:
            return float(val)
        except ValueError:
            return val

filters = {
    "gaussian": {"needs_border": True},
    "invert": {"needs_border": False},
    "contrast": {"needs_border": False},
    "hsv": {"needs_border": False},
    "levels": {"needs_border": False}
}

def rgb2hsv(rgb):
    """RGB to HSV color space conversion.

    Parameters
    ----------
    rgb : array_like
        The image in RGB format, in a 3-D array of shape (.., .., 3).

    Returns
    -------
    out : ndarray
        The image in HSV format, in a 3-D array of shape (.., .., 3).

    Raises
    ------
    ValueError
        If `rgb` is not a 3-D array of shape (.., .., 3).

    Notes
    -----
    The conversion assumes an input data range of [0, 1] for all
    color components.

    Conversion between RGB and HSV color spaces results in some loss of
    precision, due to integer arithmetic and rounding [1]_.

    References
    ----------
    .. [1] http://en.wikipedia.org/wiki/HSL_and_HSV

    Examples
    --------
    >>> from skimage import color
    >>> from skimage import data
    >>> lena = data.lena()
    >>> lena_hsv = color.rgb2hsv(lena)
    """
    arr = rgb#_prepare_colorarray(rgb)
    out = np.empty_like(arr)

    # -- V channel
    out_v = arr.max(-1)

    # -- S channel
    delta = arr.ptp(-1)
    # Ignore warning for zero divided by zero
    old_settings = np.seterr(invalid='ignore')
    out_s = delta / out_v
    out_s[delta == 0.] = 0.

    # -- H channel
    # red is max
    idx = (arr[:, :, 0] == out_v)
    out[idx, 0] = (arr[idx, 1] - arr[idx, 2]) / delta[idx]

    # green is max
    idx = (arr[:, :, 1] == out_v)
    out[idx, 0] = 2. + (arr[idx, 2] - arr[idx, 0]) / delta[idx]

    # blue is max
    idx = (arr[:, :, 2] == out_v)
    out[idx, 0] = 4. + (arr[idx, 0] - arr[idx, 1]) / delta[idx]
    out_h = (out[:, :, 0] / 6.) % 1.
    out_h[delta == 0.] = 0.

    np.seterr(**old_settings)

    # -- output
    out[:, :, 0] = out_h
    out[:, :, 1] = out_s
    out[:, :, 2] = out_v

    # remove NaN
    out[np.isnan(out)] = 0

    return out


def hsv2rgb(hsv):
    """HSV to RGB color space conversion.

    Parameters
    ----------
    hsv : array_like
        The image in HSV format, in a 3-D array of shape (.., .., 3).

    Returns
    -------
    out : ndarray
        The image in RGB format, in a 3-D array of shape (.., .., 3).

    Raises
    ------
    ValueError
        If `hsv` is not a 3-D array of shape (.., .., 3).

    Notes
    -----
    The conversion assumes an input data range of [0, 1] for all
    color components.

    Conversion between RGB and HSV color spaces results in some loss of
    precision, due to integer arithmetic and rounding [1]_.

    References
    ----------
    .. [1] http://en.wikipedia.org/wiki/HSL_and_HSV

    Examples
    --------
    >>> from skimage import data
    >>> lena = data.lena()
    >>> lena_hsv = rgb2hsv(lena)
    >>> lena_rgb = hsv2rgb(lena_hsv)
    """
    arr = hsv#_prepare_colorarray(hsv)

    hi = np.floor(arr[:, :, 0] * 6)
    f = arr[:, :, 0] * 6 - hi
    p = arr[:, :, 2] * (1 - arr[:, :, 1])
    q = arr[:, :, 2] * (1 - f * arr[:, :, 1])
    t = arr[:, :, 2] * (1 - (1 - f) * arr[:, :, 1])
    v = arr[:, :, 2]

    hi = np.dstack([hi, hi, hi]).astype(np.uint8) % 6
    out = np.choose(hi, [np.dstack((v, t, p)),
                         np.dstack((q, v, p)),
                         np.dstack((p, v, t)),
                         np.dstack((p, q, v)),
                         np.dstack((t, p, v)),
                         np.dstack((v, p, q))])

    return out

class MainHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous

    def get(self):
        self.set_header('Content-Type', 'image/png')
	url = self.get_argument("url", "", True)
        filter = self.get_argument("filter", "invert", True)
        self.__filter, self.__args = self.parse(filter)

        if self.__filter not in filters:
            print "Unknown filter"
            self.finish()
            return

        rings = 2 if filters[self.__filter]['needs_border'] else 1

        if url:
            self.load_images(url, rings)
        else:
            print "Gonna need a URL there, bub"
            self.finish()

    def coords_from_url(self, url):
        prefix, coords, suffix = re.split(r'(\d+/\d+/\d+)', url, 1)
        return prefix, [int(c) for c in coords.split("/")], suffix

    def load_images(self, url, rings):
        self.__rings = rings
        self.__results = {}
        self.__pending = 0

        prefix, coords, suffix = self.coords_from_url(url)
        self.__center_z, self.__center_x, self.__center_y = coords

        url_list = []
        for y in range(self.__center_y - rings + 1, self.__center_y + rings):
            for x in range(self.__center_x - rings + 1, self.__center_x + rings):
                temp_url = prefix + '/'.join(str(v) for v in [self.__center_z, x, y]) + suffix
                url_list.append(temp_url)
                self.__pending += 1
                http_client = tornado.httpclient.AsyncHTTPClient()
                http_client.fetch(temp_url, self.__item_callback)

    def __item_callback(self, response):
        z, x, y = self.coords_from_url(response.request.url)[1]
        offset_x = x - self.__center_x
        offset_y = y - self.__center_y

        self.__results[(offset_x, offset_y)] = response.body
        self.__pending -= 1
        if self.__pending == 0:
            self.__process_results()

    def __process_results(self):
        images = {}
        for key in self.__results:
            images[key] = Image.open(StringIO(self.__results[key]))

        rows = 1 + (self.__rings - 1) * 2
        
        size = images[(0,0)].size
        metatile = Image.new("RGBA", [t * rows for t in size])

        for key in images:
            x = size[0] * (key[0] + self.__rings - 1)
            y = size[1] * (key[1] + self.__rings - 1)
            im = images[key]
            metatile.paste(im, (x, y))

        # perform filtering
        if self.__filter == "gaussian":
            metatile = self.gaussian(metatile, self.__args["radius"])
            tile = metatile.crop((
                    (self.__rings - 1) * size[0],
                    (self.__rings - 1) * size[1],
                    (self.__rings) * size[0],
                    (self.__rings) * size[0]))

        elif self.__filter == "contrast":
            tile = self.contrast(metatile, self.__args["percent"])
        elif self.__filter == "hsv":
            tile = self.hsv(metatile, self.__args)
        elif self.__filter == "levels":
            tile = self.levels(metatile, self.__args)
        elif self.__filter == "invert":
            tile = self.invert(metatile)

        img_buff = StringIO()
        tile.save(img_buff, 'png')
        self.write(img_buff.getvalue())
        self.finish()

    def parse(self, filter_string):
        parts = filter_string.partition("(")
        filter_type = parts[0]
        args = {}
        if parts[2]:
            arg_string = parts[2]
            if arg_string[-1] == ')':
                arg_string = arg_string[:-1]
                arg_split = arg_string.split(",")
                for a in arg_split:
                    key, eq, val = a.partition("=")
                    val = classify_val(val)
                    args[key] = val
            else:
                print("Error: No terminating parenthesis in filter args")
        return filter_type, args

    def gaussian(self, image, radius):
        data = numpy.array(image)        

        kernel = range(-radius, radius + 1)
        kernel = [(d ** 2) / (2 * (radius * .5) ** 2) for d in kernel]
        kernel = [e ** -d for d in kernel]
        kernel = array(kernel, dtype=float) / sum(kernel)

        convolve1d(data, kernel, output=data, axis=0)
        convolve1d(data, kernel, output=data, axis=1)

        return Image.fromarray(data)

    def invert(self, image):
        arr = numpy.array(image)
        arr[...,0:3] = 255 - arr[...,0:3]
        return Image.fromarray(arr)

    def contrast(self, image, percent):
        print "contrast", percent
        arr = numpy.array(image)
        return Image.fromarray(arr)

    def levels(self, image, url_args):
	defaults = {
            "in_min": 0.0,
            "gamma": 1.0,
            "in_max": 255.0,
            "out_min": 0.0,
            "out_max": 255.0
	}

        args = {}
        for k in defaults:
            args[k] = float(url_args.get(k, defaults[k]))
        arr = numpy.array(image)
        arr_normal = numpy.clip((arr[...,0:3] - args["in_min"]) / (args["in_max"] - args["in_min"]), 0.0, 255.0)
        arr_gamma = numpy.power(arr_normal, args["gamma"])
        arr_rescale = numpy.clip(arr_gamma * (args["out_max"] - args["out_min"]) + args["out_min"], 0.0, 255.0)
        arr[...,0:3] = arr_rescale
        return Image.fromarray(arr)

    def hsv(self, image, url_args):
        args = {
            "hue": url_args.get("hue", 0.0) / 360.0,
            "saturation": url_args.get("saturation", 0.0) / 255.0,
            "value": url_args.get("value", 0.0) / 255.0
        }
        print "HSV"
        arr = numpy.array(image)
        rgb = arr[...,0:3] / 255.0
        hsv = rgb2hsv(rgb)
        hsv[...,0] += float(args["hue"])
        hsv[...,0] = hsv[...,0] % 1.0
        hsv[...,1] = numpy.clip(hsv[...,1] + float(args["saturation"]), 0.0, 1.0)
        hsv[...,2] = numpy.clip(hsv[...,2] + float(args["value"]), 0.0, 1.0)
        arr[...,0:3] = hsv2rgb(hsv) * 255.0
        return Image.fromarray(arr)

application = tornado.web.Application([
    (r"/", MainHandler),
])

if __name__ == "__main__":
    application.listen(8888)
    tornado.ioloop.IOLoop.instance().start()
